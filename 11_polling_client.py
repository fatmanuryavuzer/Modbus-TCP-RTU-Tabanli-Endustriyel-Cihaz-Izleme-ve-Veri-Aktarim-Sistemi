import csv
import shutil
import time
from datetime import datetime
from pathlib import Path

from modbus_adapters import create_adapter
from config_validator import (
    ConfigurationError,
    validate_configuration
)
from database import (
    append_reading_history,
    count_reading_history_older_than,
    delete_reading_history_older_than,
    load_configuration_from_database,
    load_device_health_from_database,
    replace_current_readings,
    replace_device_health
)
from simulation_data import start_simulation


LOG_FILE = Path(__file__).with_name(
    "modbus_readings_log.csv"
)

CSV_FIELDNAMES = [
    "device_key",
    "device_name",
    "measurement_key",
    "measurement_name",
    "protocol",
    "unit_id",
    "address",
    "count",
    "data_type",
    "raw_value",
    "value",
    "unit",
    "timestamp",
    "status",
    "error"
]

READING_HISTORY_RETENTION_DAYS = 30
HISTORY_CLEANUP_INTERVAL_SECONDS = 3600


def load_configuration():
    """
    SQLite ayarlarını okur
    ve polling'in kullandığı Python sözlüğüne dönüştürür.
    """

    configuration = load_configuration_from_database()

    validate_configuration(configuration)

    return configuration


def create_device_health_record(device):
    """Bir cihaz için başlangıç sağlık kaydı oluşturur."""

    return {
        "device_key": device.get("key", ""),
        "device_name": device.get(
            "name",
            "Bilinmeyen cihaz"
        ),
        "protocol": device.get(
            "protocol",
            "tcp"
        ),
        "unit_id": device.get("unit_id"),
        "status": (
            "ONLINE"
            if device.get("enabled", True)
            else "DISABLED"
        ),
        "total_measurements": len(
            device.get("measurements", [])
        ),
        "successful_measurements": 0,
        "failed_measurements": 0,
        "consecutive_error_cycles": 0,
        "last_successful_reading": None,
        "last_error": None,
        "last_error_at": None,
        "updated_at": None
    }


def load_device_health(devices):
    """SQLite sağlık kayıtlarını yükler veya başlangıç kaydı oluşturur."""

    health_by_device = {
        health["device_key"]: health
        for health in load_device_health_from_database()
        if health.get("device_key")
    }

    for device in devices:
        device_key = device.get("key")

        if not device_key:
            continue

        health = health_by_device.get(device_key)

        if health is None:
            health = create_device_health_record(device)

        saved_status = health.get(
            "status",
            "UNKNOWN"
        )

        health.update(
            {
                "device_name": device.get(
                    "name",
                    "Bilinmeyen cihaz"
                ),
                "protocol": device.get(
                    "protocol",
                    "tcp"
                ),
                "unit_id": device.get("unit_id"),
                "total_measurements": len(
                    device.get("measurements", [])
                ),
                "status": (
                    (
                        "UNKNOWN"
                        if saved_status == "DISABLED"
                        else saved_status
                    )
                    if device.get("enabled", True)
                    else "DISABLED"
                )
            }
        )

        health_by_device[device_key] = health

    return health_by_device


def update_device_health(
    devices,
    readings,
    health_by_device
):
    """Son okuma turuna göre cihazların genel sağlık durumunu günceller."""

    cycle_timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    for device in devices:
        device_key = device.get("key")

        if not device_key:
            continue

        device_readings = [
            reading
            for reading in readings
            if reading.get("device_key") == device_key
        ]

        successful_readings = [
            reading
            for reading in device_readings
            if reading.get("status") == "OK"
        ]

        failed_readings = [
            reading
            for reading in device_readings
            if reading.get("status") != "OK"
        ]

        health = health_by_device[device_key]

        if not device.get("enabled", True):
            health.update(
                {
                    "status": "DISABLED",
                    "successful_measurements": 0,
                    "failed_measurements": 0,
                    "consecutive_error_cycles": 0,
                    "last_error": None,
                    "updated_at": cycle_timestamp
                }
            )
            continue

        health["successful_measurements"] = len(
            successful_readings
        )
        health["failed_measurements"] = len(
            failed_readings
        )
        health["updated_at"] = cycle_timestamp

        if not device_readings:
            health["status"] = "UNKNOWN"
            continue

        if not failed_readings:
            health["status"] = "ONLINE"
            health["consecutive_error_cycles"] = 0

            successful_timestamps = [
                reading.get("timestamp")
                for reading in successful_readings
                if reading.get("timestamp")
            ]

            if successful_timestamps:
                health["last_successful_reading"] = max(
                    successful_timestamps
                )

        elif not successful_readings:
            health["status"] = "OFFLINE"
            health["consecutive_error_cycles"] = int(
                health.get("consecutive_error_cycles", 0)
            ) + 1

        else:
            health["status"] = "DEGRADED"
            health["consecutive_error_cycles"] = int(
                health.get("consecutive_error_cycles", 0)
            ) + 1

        if failed_readings:
            health["last_error"] = next(
                (
                    reading.get("error")
                    for reading in failed_readings
                    if reading.get("error")
                ),
                "Bilinmeyen okuma hatası"
            )
            health["last_error_at"] = cycle_timestamp


def show_device_health(
    devices,
    health_by_device
):
    """Cihaz sağlık özetini terminalde gösterir."""

    print()
    print("--- Cihaz sağlık durumları ---")

    for device in devices:
        if not device.get("enabled", True):
            print(
                f"{device.get('name', 'Bilinmeyen cihaz')} | "
                "Durum: DEVRE DIŞI | Polling atlandı"
            )
            continue

        health = health_by_device.get(
            device.get("key")
        )

        if not health:
            continue

        print(
            f"{health['device_name']} | "
            f"Durum: {health['status']} | "
            f"Başarılı: "
            f"{health['successful_measurements']}/"
            f"{health['total_measurements']} | "
            f"Sorunlu ardışık tur: "
            f"{health['consecutive_error_cycles']}"
        )


def has_memory_rtu_device(devices):
    """Kod içi RTU simülasyonu gereken cihaz var mı kontrol eder."""

    return any(
        str(device.get("protocol", "tcp")).lower() == "rtu"
        and device.get("transport") == "memory"
        for device in devices
    )


def read_measurement(
    device,
    measurement,
    transaction_id
):
    """
    Bir cihazdaki ölçümü adaptör üzerinden okur.
    """

    unit_id = int(device["unit_id"])

    address = int(
        measurement["address"]
    )
    count = int(
        measurement["count"]
    )
    scale = float(
        measurement["scale"]
    )

    data_type = measurement.get(

        "data_type",
        "u16"
    )

    unit = measurement["unit"]
    measurement_name = measurement["name"]

    print()
    print(f"Cihaz: {device['name']}")
    print(f"Ölçüm: {measurement_name}")
    print(f"Unit ID: {unit_id}")
    print(f"Register adresi: {address}")
    print(f"Register adedi: {count}")

    adapter = create_adapter(device)

    register_values = adapter.read_registers(
        device,
        measurement,
        transaction_id,
        data_type
    )

    print("Register değerleri:")
    print(register_values)

    real_values = [
        raw_value * scale
        for raw_value in register_values
    ]

    for raw_value, real_value in zip(
        register_values,
        real_values
    ):
        print(
            f"{measurement_name}: "
            f"{raw_value} x {scale} = "
            f"{real_value:.1f} {unit}"
        )

    # Okunan bilgileri arayüzün kullanabileceği
    # düzenli bir kayıt olarak hazırladım
    reading = {
        "device_key": device.get("key"),
        "device_name": device.get("name"),
        "measurement_key": measurement.get("key"),
        "measurement_name": measurement_name,
        "protocol": device.get(
            "protocol",
            "tcp"
        ),
        "unit_id": unit_id,
        "address": address,
        "count": count,
        "data_type": data_type,
        "raw_value": (
            register_values[0]
            if len(register_values) == 1
            else register_values
        ),
        "value": (
            real_values[0]
            if len(real_values) == 1
            else real_values
        ),
        "unit": unit,
        "timestamp": datetime.now().isoformat(
            timespec="seconds"
        ),
        "status": "OK"
    }

    return reading


def show_current_readings(readings):
    """
    Bir okuma turunda oluşturulan kayıtları gösterir.
    """

    print()
    print("--- Düzenli kayıtlar ---")

    for reading in readings:
        print(
            f"{reading['device_name']} | "
            f"{reading['measurement_name']} | "
            f"Değer: {reading['value']} {reading['unit']} | "
            f"Durum: {reading['status']}"
        )


def append_readings_to_csv(readings):
    """
    Okuma kayıtlarını CSV log dosyasına ekler.
    """

    if not readings:
        return

    migrate_csv_schema()

    file_exists = LOG_FILE.exists()

    with LOG_FILE.open(
        "a",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDNAMES
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(readings)

    print(
        f"Log kaydedildi: {LOG_FILE}"
    )


def migrate_csv_schema():
    """Eski CSV başlığını yeni ölçüm alanlarıyla güvenli şekilde günceller."""

    if not LOG_FILE.exists():
        return

    with LOG_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []

        if existing_fieldnames == CSV_FIELDNAMES:
            return

        existing_rows = list(reader)

    backup_file = LOG_FILE.with_suffix(
        LOG_FILE.suffix + ".bak"
    )

    if not backup_file.exists():
        shutil.copy2(
            LOG_FILE,
            backup_file
        )

    with LOG_FILE.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDNAMES
        )
        writer.writeheader()

        for existing_row in existing_rows:
            normalized_row = {
                fieldname: existing_row.get(
                    fieldname,
                    ""
                )
                for fieldname in CSV_FIELDNAMES
            }

            normalized_row["protocol"] = existing_row.get(
                "protocol",
                "tcp"
            ) or "tcp"

            normalized_row["error"] = existing_row.get(
                "error",
                ""
            ) or ""

            writer.writerow(normalized_row)

def collect_one_cycle(
    devices,
    transaction_id
):
    """
    Bir okuma turunda cihazlardan veri toplar.
    """

    current_readings = []

    for device in devices:
        if not device.get("enabled", True):
            print(
                f"{device.get('name', 'Bilinmeyen cihaz')} "
                "devre dışı; okuma atlandı."
            )
            continue

        measurements = device.get(
            "measurements",
            []
        )

        if not measurements:
            print(
                f"{device['name']} için ölçüm bulunamadı."
            )
            continue

        for measurement in measurements:
            try:
                reading = read_measurement(
                    device,
                    measurement,
                    transaction_id
                )

                current_readings.append(
                    reading
                )

            except Exception as error:
                print(
                    f"HATA: {device['name']} - "
                    f"{measurement['name']} okunamadı: {error}"
                )

                error_reading = {
                    "device_key": device.get("key", ""),
                    "device_name": device.get(
                        "name",
                        "Bilinmeyen cihaz"
                    ),
                    "measurement_key": measurement.get(
                        "key",
                        ""
                    ),
                    "measurement_name": measurement.get(
                        "name",
                        "Bilinmeyen ölçüm"
                    ),
                    "protocol": device.get(
                        "protocol",
                        "tcp"
                    ),
                    "unit_id": device.get("unit_id"),
                    "address": measurement.get("address"),
                    "count": measurement.get("count"),
                    "data_type": measurement.get("data_type"),
                    "raw_value": None,
                    "value": None,
                    "unit": measurement.get("unit", ""),
                    "timestamp": datetime.now().isoformat(
                        timespec="seconds"
                    ),
                    "status": "HATA",
                    "error": str(error)
                }

                current_readings.append(
                    error_reading
                )

            transaction_id += 1

            if transaction_id > 65535:
                transaction_id = 1

    return current_readings, transaction_id




def main():
    """
    SQLite'taki etkin cihazları sürekli olarak okur.
    """

    configuration = load_configuration()

    devices = configuration.get(
        "devices",
        []
    )

    if not devices:
        raise ValueError(
            "Ayar dosyasında hiç cihaz bulunamadı."
        )

    if has_memory_rtu_device(devices):
        start_simulation()
        print(
            "Kod içi RTU simülasyon veri üreticisi çalışıyor."
        )

    device_health = load_device_health(
        devices
    )

    transaction_id = 1
    last_history_cleanup_at = time.monotonic()

    while True:
        configuration = load_configuration()
        devices = configuration.get(
            "devices",
            []
        )

        device_health = load_device_health(
            devices
        )

        print()
        print("--- Yeni okuma turu başlıyor ---")

        current_readings, transaction_id = collect_one_cycle(
            devices,
            transaction_id
        )

        update_device_health(
            devices,
            current_readings,
            device_health
        )

        replace_current_readings(
            current_readings
        )
        replace_device_health(
            devices,
            device_health
        )
        append_reading_history(
            current_readings
        )

        cleanup_age = (
            time.monotonic()
            - last_history_cleanup_at
        )

        if cleanup_age >= HISTORY_CLEANUP_INTERVAL_SECONDS:
            old_record_count = count_reading_history_older_than(
                READING_HISTORY_RETENTION_DAYS
            )

            deleted_record_count = 0

            if old_record_count:
                deleted_record_count = (
                    delete_reading_history_older_than(
                        READING_HISTORY_RETENTION_DAYS
                    )
                )

            print(
                "30 günlük okuma geçmişi temizliği: "
                f"{old_record_count} eski kayıt bulundu, "
                f"{deleted_record_count} kayıt silindi."
            )

            last_history_cleanup_at = time.monotonic()

        show_current_readings(
            current_readings
        )

        show_device_health(
            devices,
            device_health
        )

        append_readings_to_csv(
            current_readings
        )

        successful_count = sum(
            reading["status"] == "OK"
            for reading in current_readings
        )

        print(
            f"Bu turda {successful_count} "
            "başarılı kayıt oluşturuldu."
        )

        print()
        print("Tur tamamlandı. 5 saniye bekleniyor...")
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nPolling kullanıcı tarafından durduruldu."
        )

    except FileNotFoundError:
        print(
            "HATA: SQLite veritabanı bulunamadı."
        )

    except ConfigurationError as error:
        print(
            "HATA: SQLite cihaz ayarları doğrulaması başarısız."
        )
        print(error)

    except Exception as error:
        print(
            f"HATA: {error}"
        )
