"""05_device_config.json içeriğini SQLite veritabanına taşır."""

import json
from pathlib import Path

from config_validator import (
    ConfigurationError,
    validate_configuration
)
from database import (
    get_connection,
    create_tables
)


CONFIG_FILE = Path(__file__).with_name(
    "05_device_config.json"
)


def load_configuration():
    """JSON ayar dosyasını okur ve doğrular."""

    with CONFIG_FILE.open(
        "r",
        encoding="utf-8"
    ) as file:
        configuration = json.load(file)

    validate_configuration(configuration)

    return configuration


def ensure_database_is_empty(connection):
    """Mevcut cihaz varsa migration'ın üzerine yazmasını engeller."""

    device_count = connection.execute(
        "SELECT COUNT(*) AS count FROM devices"
    ).fetchone()["count"]

    measurement_count = connection.execute(
        "SELECT COUNT(*) AS count FROM measurements"
    ).fetchone()["count"]

    if device_count or measurement_count:
        raise RuntimeError(
            "SQLite veritabanında zaten cihaz veya ölçüm kayıtları var. "
            "Mevcut kayıtların üzerine yazılmadı."
        )


def insert_simulation_settings(
    connection,
    settings
):
    """Genel simülasyon ayarlarını SQLite'a ekler."""

    connection.execute(
        """
        UPDATE simulation_settings
        SET
            rtu_enabled = ?,
            serial_port = ?,
            baudrate = ?,
            parity = ?,
            stopbits = ?,
            bytesize = ?,
            timeout = ?
        WHERE settings_id = 1
        """,
        (
            int(settings.get("rtu_enabled", False)),
            settings.get("serial_port", ""),
            settings.get("baudrate", 9600),
            settings.get("parity", "N"),
            settings.get("stopbits", 1),
            settings.get("bytesize", 8),
            settings.get("timeout", 1)
        )
    )


def insert_device(
    connection,
    device
):
    """Bir cihazı ekler ve oluşan id değerini döndürür."""

    cursor = connection.execute(
        """
        INSERT INTO devices (
            device_key,
            device_name,
            protocol,
            transport,
            host,
            port,
            serial_port,
            baudrate,
            parity,
            stopbits,
            bytesize,
            timeout,
            retry_count,
            retry_delay,
            unit_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device["key"],
            device["name"],
            device["protocol"].lower(),
            device.get("transport"),
            device.get("host"),
            device.get("port"),
            device.get("serial_port"),
            device.get("baudrate"),
            device.get("parity"),
            device.get("stopbits"),
            device.get("bytesize"),
            device.get("timeout", 3),
            device.get("retry_count", 2),
            device.get("retry_delay", 0.5),
            device["unit_id"]
        )
    )

    return cursor.lastrowid


def insert_measurements(
    connection,
    device_id,
    measurements
):
    """Bir cihaza ait tüm ölçümleri ekler."""

    for measurement in measurements:
        connection.execute(
            """
            INSERT INTO measurements (
                device_id,
                measurement_key,
                measurement_name,
                function_code,
                address,
                count,
                data_type,
                scale,
                unit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                measurement["key"],
                measurement["name"],
                measurement["function_code"],
                measurement["address"],
                measurement["count"],
                measurement["data_type"],
                measurement["scale"],
                measurement["unit"]
            )
        )


def migrate_configuration(configuration):
    """JSON içeriğini tek transaction içinde SQLite'a taşır."""

    create_tables()

    with get_connection() as connection:
        ensure_database_is_empty(connection)

        insert_simulation_settings(
            connection,
            configuration.get("simulation", {})
        )

        device_count = 0
        measurement_count = 0

        for device in configuration["devices"]:
            device_id = insert_device(
                connection,
                device
            )
            insert_measurements(
                connection,
                device_id,
                device["measurements"]
            )

            device_count += 1
            measurement_count += len(
                device["measurements"]
            )

    return device_count, measurement_count


def main():
    """Migration işlemini komut satırından çalıştırır."""

    configuration = load_configuration()
    device_count, measurement_count = migrate_configuration(
        configuration
    )

    print(
        f"{device_count} cihaz SQLite'a aktarıldı."
    )
    print(
        f"{measurement_count} ölçüm SQLite'a aktarıldı."
    )
    print(
        "JSON ayar dosyası korunuyor; henüz silinmedi."
    )


if __name__ == "__main__":
    try:
        main()

    except FileNotFoundError:
        print(
            "HATA: 05_device_config.json bulunamadı."
        )

    except json.JSONDecodeError as error:
        print(
            "HATA: JSON dosyasının biçimi hatalı."
        )
        print(error)

    except ConfigurationError as error:
        print(
            "HATA: Ayar doğrulaması başarısız."
        )
        print(error)

    except Exception as error:
        print(
            f"HATA: {error}"
        )
