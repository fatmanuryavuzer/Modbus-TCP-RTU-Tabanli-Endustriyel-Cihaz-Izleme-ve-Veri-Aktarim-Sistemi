import csv
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file
)

from config_validator import (
    ConfigurationError,
    validate_new_device,
    validate_updated_device
)
from database import (
    add_device_with_measurements,
    add_devices_with_measurements_bulk,
    create_transfer_history,
    delete_device,
    load_expired_successful_transfer_files,
    load_transfer_history,
    load_reading_history_from_database,
    load_current_readings_from_database,
    load_device_health_from_database,
    load_configuration_from_database,
    set_device_enabled,
    set_devices_enabled,
    delete_devices,
    update_transfer_history,
    update_device_with_measurements,
    update_measurement_register
)
from transfer_service import (
    build_transfer_content,
    cleanup_expired_successful_transfer_files,
    delete_transfer_file,
    save_transfer_file,
    send_via_ftp,
    send_via_sftp,
    send_via_json_api
)


app = Flask(__name__)

MIN_TRANSFER_HOURS = 1
MAX_TRANSFER_HOURS = 24


def parse_transfer_hours(value):
    """Saat aralığını tam sayıya çevirir; geçersiz değerde None döndürür."""

    if isinstance(
        value,
        bool
    ):
        return None

    try:
        numeric_value = float(
            value
        )
    except (TypeError, ValueError):
        return None

    if not numeric_value.is_integer():
        return None

    return int(
        numeric_value
    )


def parse_json_integer(value):
    """JSON içindeki tam sayı alanını bool değerlerini kabul etmeden okur."""

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float) and value.is_integer():
        return int(value)

    return None

def load_current_readings():
    """Arayüzün son ölçüm turunu SQLite'tan okur."""

    return load_current_readings_from_database()


def load_device_health():
    """Cihazların genel sağlık kayıtlarını yükler."""

    return load_device_health_from_database()


def validate_transfer_request(payload):
    """Aktarım isteğindeki alanları kontrol eder."""

    errors = []

    if not isinstance(payload, dict):
        return [
            "İstek gövdesi JSON nesnesi olmalı."
        ]

    method = payload.get(
        "method",
        ""
    )

    file_format = payload.get(
        "format",
        ""
    )

    transfer_window = payload.get(
        "window",
        "manual"
    )

    destination = payload.get(
        "destination",
        ""
    ).strip()

    if method not in {
        "ftp",
        "sftp",
        "json-api"
    }:
        errors.append(
            "Geçersiz aktarım yöntemi."
        )

    if file_format not in {
        "csv",
        "json"
    }:
        errors.append(
            "Geçersiz dosya formatı."
        )

    if transfer_window not in {
        "manual",
        "custom"
    }:
        errors.append(
            "Geçersiz aktarım zaman aralığı."
        )
    elif transfer_window == "custom":
        transfer_hours = parse_transfer_hours(
            payload.get(
                "hours"
            )
        )

        if transfer_hours is None:
            errors.append(
                "Özel saat aralığı tam sayı olarak girilmelidir."
            )
        elif not (
            MIN_TRANSFER_HOURS
            <= transfer_hours
            <= MAX_TRANSFER_HOURS
        ):
            errors.append(
                (
                    "Saat aralığı 1 ile 24 arasında olmalıdır."
                )
            )

    if (
        method == "json-api"
        and file_format != "json"
    ):
        errors.append(
            "JSON API için dosya formatı JSON olmalı."
        )

    if not destination:
        errors.append(
            "Hedef adres boş bırakılamaz."
        )
    else:
        parsed_url = urlparse(
            destination
        )

        expected_scheme = {
            "ftp": "ftp",
            "sftp": "sftp",
            "json-api": "http"
        }.get(method)

        valid_scheme = (
            parsed_url.scheme == expected_scheme
            or (
                method == "json-api"
                and parsed_url.scheme == "https"
            )
        )

        if not valid_scheme:
            errors.append(
                "Hedef adres seçilen yöntemle uyumlu değil."
            )

        if not parsed_url.hostname:
            errors.append(
                "Hedef adres içinde sunucu adı bulunamadı."
            )

    if method in {
        "ftp",
        "sftp"
    }:
        if not payload.get("username"):
            errors.append(
                "Kullanıcı adı girilmelidir."
            )

        if not payload.get("password"):
            errors.append(
                "Parola girilmelidir."
            )

    return errors


@app.route("/")
def home():
    readings = load_current_readings()

    return render_template(
        "index.html",
        readings=readings
    )

@app.route("/api/readings")
def api_readings():
    readings = load_current_readings()

    return jsonify(
        readings
    )


@app.route("/api/history")
def api_history():
    """Geçmiş ölçümleri filtreleyerek API üzerinden döndürür."""

    history = load_reading_history_from_database(
        device_key=request.args.get(
            "device_key"
        ),
        measurement_key=request.args.get(
            "measurement_key"
        ),
        start_date=request.args.get(
            "start_date"
        ),
        end_date=request.args.get(
            "end_date"
        ),
        limit=request.args.get(
            "limit",
            100
        )
    )

    return jsonify(
        history
    )


@app.route(
    "/api/transfers",
    methods=["POST"]
)
def api_transfers():
    """Aktarım isteğini doğrular ve seçili kayıt sayısını döndürür."""

    payload = request.get_json(
        silent=True
    )

    errors = validate_transfer_request(
        payload
    )

    if errors:
        return jsonify(
            {
                "ok": False,
                "errors": errors
            }
        ), 400

    expired_transfer_files = (
        load_expired_successful_transfer_files(
            retention_days=7
        )
    )

    try:
        cleanup_expired_successful_transfer_files(
            expired_transfer_files
        )
    except OSError:
        # Temizlik başarısız olsa bile yeni aktarımı engelleme.
        pass

    filters = payload.get(
        "filters",
        {}
    )

    if not isinstance(filters, dict):
        return jsonify(
            {
                "ok": False,
                "errors": [
                    "filters alanı JSON nesnesi olmalı."
                ]
            }
        ), 400

    transfer_window = payload.get(
        "window",
        "manual"
    )

    transfer_hours = (
        parse_transfer_hours(
            payload.get(
                "hours"
            )
        )
        if transfer_window == "custom"
        else None
    )

    history_filters = {
        "device_key": filters.get(
            "device_key"
        ),
        "measurement_key": filters.get(
            "measurement_key"
        ),
        "limit": None
    }

    if transfer_window == "manual":
        history_filters.update(
            {
                "start_date": filters.get(
                    "start_date"
                ),
                "end_date": filters.get(
                    "end_date"
                )
            }
        )
    else:
        now = datetime.now().replace(
            microsecond=0
        )

        history_filters.update(
            {
                "start_timestamp": (
                    now - timedelta(
                        hours=transfer_hours
                    )
                ).isoformat(),
                "end_timestamp": now.isoformat()
            }
        )

    selected_rows = load_reading_history_from_database(
        **history_filters
    )

    if not selected_rows:
        return jsonify(
            {
                "ok": False,
                "errors": [
                    (
                        "Seçilen filtre ve zaman aralığında "
                        "aktarılacak kayıt bulunamadı."
                    )
                ]
            }
        ), 400

    try:
        content_bytes, file_name, mime_type = (
            build_transfer_content(
                selected_rows,
                payload.get("format")
            )
        )
    except ValueError as error:
        return jsonify(
            {
                "ok": False,
                "errors": [
                    str(error)
                ]
            }
        ), 400

    try:
        local_file = save_transfer_file(
            content_bytes=content_bytes,
            file_name=file_name,
            window=payload.get(
                "window",
                "manual"
            )
        )
    except OSError as error:
        return jsonify(
            {
                "ok": False,
                "errors": [
                    (
                        "Aktarım dosyası yerel klasöre kaydedilemedi: "
                        f"{error}"
                    )
                ]
            }
        ), 500

    transfer_history_id = create_transfer_history(
        file_name=local_file["file_name"],
        method=payload["method"],
        file_format=payload["format"],
        transfer_window=payload.get(
            "window",
            "manual"
        ),
        window_hours=transfer_hours,
        record_count=len(selected_rows),
        content_size=len(content_bytes),
        local_path=local_file["path"],
        destination=payload["destination"],
        filters={
            "device_key": filters.get(
                "device_key"
            ) or "",
            "measurement_key": filters.get(
                "measurement_key"
            ) or "",
            "start_date": filters.get(
                "start_date"
            ) or "",
            "end_date": filters.get(
                "end_date"
            ) or ""
        }
    )

    transfer_result = None

    transfer_method = payload.get(
        "method"
    )

    if transfer_method in {
        "ftp",
        "sftp",
        "json-api"
    }:
        try:
            send_functions = {
                "ftp": send_via_ftp,
                "sftp": send_via_sftp,
                "json-api": send_via_json_api
            }

            send_function = send_functions[
                transfer_method
            ]

            transfer_result = send_function(
                content_bytes=content_bytes,
                file_name=file_name,
                destination=payload.get(
                    "destination"
                ),
                username=payload.get(
                    "username"
                ),
                password=payload.get(
                    "password"
                )
            )

            update_transfer_history(
                transfer_history_id,
                "SUCCESS"
            )

            try:
                local_file["deleted_after_transfer"] = (
                    delete_transfer_file(
                        local_file
                    )
                )
            except OSError as cleanup_error:
                # Gönderim başarılıdır; yalnızca geçici dosya temizliği
                # başarısız olduysa bunu arayüze bildirmek yeterlidir.
                local_file[
                    "deleted_after_transfer"
                ] = False
                local_file[
                    "cleanup_error"
                ] = str(
                    cleanup_error
                )
        except Exception as error:
            update_transfer_history(
                transfer_history_id,
                "FAILED",
                str(error)
            )

            return jsonify(
                {
                    "ok": False,
                    "errors": [
                        (
                            f"{transfer_method.upper()} gönderimi "
                            f"başarısız: {error}"
                        )
                    ],
                    "local_file": local_file,
                    "transfer_history_id": transfer_history_id
                }
            ), 502

    return jsonify(
        {
            "ok": True,
            "message": (
                f"{transfer_method.upper()} dosya gönderimi başarılı."
                if transfer_method in {
                    "ftp",
                    "sftp",
                    "json-api"
                }
                else (
                    "Aktarım isteği doğrulandı. "
                    "Bu yöntem için gerçek gönderim "
                    "bir sonraki adımda yapılacak."
                )
            ),
            "method": payload.get("method"),
            "format": payload.get("format"),
            "record_count": len(selected_rows),
            "file_name": file_name,
            "mime_type": mime_type,
            "content_size": len(content_bytes),
            "local_file": local_file,
            "transfer_history_id": transfer_history_id,
            "transfer": transfer_result
        }
    )


@app.route("/api/transfers/history")
def api_transfer_history():
    """Son aktarım sonuçlarını arayüze döndürür."""

    return jsonify(
        load_transfer_history(
            request.args.get(
                "limit",
                20
            )
        )
    )


@app.route("/api/health")
def api_health():
    """Cihaz sağlık kayıtlarını API üzerinden döndürür."""

    health = load_device_health()

    return jsonify(
        health
    )


@app.route("/api/devices", methods=["GET"])
def api_devices():
    """SQLite'taki cihaz tanımlarını API üzerinden döndürür."""

    configuration = load_configuration_from_database()

    return jsonify(
        configuration["devices"]
    )


@app.route(
    "/api/devices/<device_key>/measurements/<measurement_key>",
    methods=["PATCH"]
)
def api_update_measurement_register(device_key, measurement_key):
    """Tablodan bir ölçümün register adresini ve adetini günceller."""

    payload = request.get_json(
        silent=True
    )

    if not isinstance(payload, dict):
        return jsonify(
            {
                "ok": False,
                "error": "İstek gövdesi JSON nesnesi olmalı."
            }
        ), 400

    address = parse_json_integer(
        payload.get("address")
    )
    count = parse_json_integer(
        payload.get("count")
    )

    if address is None or not 0 <= address <= 65535:
        return jsonify(
            {
                "ok": False,
                "error": "Register adresi 0 ile 65535 arasında tam sayı olmalı."
            }
        ), 400

    if count is None or not 1 <= count <= 125:
        return jsonify(
            {
                "ok": False,
                "error": "Register adedi 1 ile 125 arasında tam sayı olmalı."
            }
        ), 400

    if address + count > 65536:
        return jsonify(
            {
                "ok": False,
                "error": "Register aralığı 65535 adresini aşamaz."
            }
        ), 400

    result = update_measurement_register(
        device_key,
        measurement_key,
        address,
        count
    )

    if not result["ok"]:
        return jsonify(result), result.get("status_code", 400)

    return jsonify(
        {
            "ok": True,
            "message": "Register adresi ve adedi güncellendi.",
            "device_key": device_key,
            "measurement_key": measurement_key,
            "address": address,
            "count": count
        }
    )


@app.route("/api/devices", methods=["POST"])
def api_add_device():
    """Doğrulanmış yeni cihazı ve ölçümlerini SQLite'a ekler."""

    device = request.get_json(
        silent=True
    )

    if not isinstance(device, dict):
        return jsonify(
            {
                "ok": False,
                "error": "İstek gövdesi JSON nesnesi olmalı."
            }
        ), 400

    try:
        configuration = load_configuration_from_database()

        validate_new_device(
            device,
            configuration["devices"]
        )

        device_id = add_device_with_measurements(
            device
        )
    except ConfigurationError as error:
        return jsonify(
            {
                "ok": False,
                "error": str(error)
            }
        ), 400
    except sqlite3.IntegrityError as error:
        return jsonify(
            {
                "ok": False,
                "error": "Cihaz veritabanı kısıtlarına uymuyor.",
                "detail": str(error)
            }
        ), 409

    return jsonify(
        {
            "ok": True,
            "message": "Cihaz başarıyla eklendi.",
            "device_id": device_id
        }
    ), 201


def _read_uploaded_csv(file_storage, required_headers, label, errors):
    """Yüklenen CSV dosyasını başlıklarıyla birlikte okur."""

    if file_storage is None:
        errors.append(
            f"{label} dosyası seçilmedi."
        )
        return []

    try:
        text = file_storage.read().decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError:
        errors.append(
            f"{label} UTF-8 biçiminde olmalı."
        )
        return []

    reader = csv.DictReader(
        io.StringIO(text, newline="")
    )
    raw_headers = reader.fieldnames or []
    headers = [
        header.strip()
        for header in raw_headers
        if header is not None
    ]
    missing_headers = [
        header
        for header in required_headers
        if header not in headers
    ]

    if missing_headers:
        errors.append(
            f"{label} eksik sütun içeriyor: "
            f"{', '.join(missing_headers)}."
        )
        return []

    reader.fieldnames = headers
    rows = []

    for row in reader:
        if not row or all(
            not str(value or "").strip()
            for value in row.values()
            if value is not None
        ):
            continue

        rows.append(
            {
                key: str(value or "").strip()
                for key, value in row.items()
                if key is not None
            }
        )

    return rows


def _csv_required_text(row, field_name, location, errors):
    """CSV satırındaki zorunlu metin alanını alır."""

    value = row.get(field_name, "").strip()

    if not value:
        errors.append(
            f"{location}: '{field_name}' boş olamaz."
        )

    return value


def _csv_optional_number(
    row,
    field_name,
    location,
    errors,
    integer=False
):
    """CSV'deki isteğe bağlı sayısal alanı doğru tipe çevirir."""

    raw_value = row.get(field_name, "").strip()

    if not raw_value:
        return None

    try:
        return int(raw_value) if integer else float(raw_value)
    except ValueError:
        errors.append(
            f"{location}: '{field_name}' sayısal olmalı."
        )
        return None


def _csv_required_number(
    row,
    field_name,
    location,
    errors,
    integer=False
):
    """CSV'deki zorunlu sayısal alanı doğru tipe çevirir."""

    value = _csv_optional_number(
        row,
        field_name,
        location,
        errors,
        integer=integer
    )

    if value is None and not row.get(field_name, "").strip():
        errors.append(
            f"{location}: '{field_name}' boş olamaz."
        )

    return value


def _parse_devices_csv(
    rows,
    errors,
    allow_missing_unit_id=False
):
    """Cihaz CSV satırlarını API cihaz sözlüklerine dönüştürür."""

    devices = []
    device_keys = set()

    for index, row in enumerate(rows, start=2):
        location = f"devices.csv satır {index}"
        device_key = _csv_required_text(
            row,
            "key",
            location,
            errors
        )

        if device_key in device_keys and device_key:
            errors.append(
                f"{location}: cihaz key değeri tekrar ediyor: "
                f"'{device_key}'."
            )
        elif device_key:
            device_keys.add(device_key)

        protocol = _csv_required_text(
            row,
            "protocol",
            location,
            errors
        ).lower()
        enabled_text = row.get("enabled", "").strip().lower()
        enabled = enabled_text not in {
            "false",
            "0",
            "hayır",
            "no"
        }
        timeout = _csv_optional_number(
            row,
            "timeout",
            location,
            errors
        )

        if timeout is None and not row.get("timeout", "").strip():
            timeout = 3

        device = {
            "key": device_key,
            "name": _csv_required_text(
                row,
                "name",
                location,
                errors
            ),
            "protocol": protocol,
            "enabled": enabled,
            "unit_id": (
                _csv_optional_number(
                    row,
                    "unit_id",
                    location,
                    errors,
                    integer=True
                )
                if allow_missing_unit_id
                else _csv_required_number(
                    row,
                    "unit_id",
                    location,
                    errors,
                    integer=True
                )
            ),
            "timeout": timeout,
            "retry_count": _csv_optional_number(
                row,
                "retry_count",
                location,
                errors,
                integer=True
            ),
            "retry_delay": _csv_optional_number(
                row,
                "retry_delay",
                location,
                errors
            )
        }

        if device["retry_count"] is None:
            device["retry_count"] = 2

        if device["retry_delay"] is None:
            device["retry_delay"] = 0.5

        if protocol == "tcp":
            device["host"] = row.get("host", "").strip()
            device["port"] = _csv_required_number(
                row,
                "port",
                location,
                errors,
                integer=True
            )
        else:
            device["transport"] = (
                row.get("transport", "").strip()
                or "memory"
            )
            serial_port = row.get(
                "serial_port",
                ""
            ).strip()

            if serial_port:
                device["serial_port"] = serial_port

            for field_name, integer in (
                ("baudrate", True),
                ("bytesize", True)
            ):
                value = _csv_optional_number(
                    row,
                    field_name,
                    location,
                    errors,
                    integer=integer
                )

                if value is not None:
                    device[field_name] = value

            parity = row.get("parity", "").strip()
            stopbits = _csv_optional_number(
                row,
                "stopbits",
                location,
                errors
            )

            if parity:
                device["parity"] = parity

            if stopbits is not None:
                device["stopbits"] = stopbits

        device["measurements"] = []
        devices.append(device)

    return devices


def _parse_measurements_csv(rows, errors):
    """Ölçüm CSV satırlarını ölçüm sözlüklerine dönüştürür."""

    measurements = []

    for index, row in enumerate(rows, start=2):
        location = f"measurements.csv satır {index}"
        measurements.append(
            {
                "device_key": _csv_required_text(
                    row,
                    "device_key",
                    location,
                    errors
                ),
                "key": _csv_required_text(
                    row,
                    "key",
                    location,
                    errors
                ),
                "name": _csv_required_text(
                    row,
                    "name",
                    location,
                    errors
                ),
                "function_code": _csv_required_number(
                    row,
                    "function_code",
                    location,
                    errors,
                    integer=True
                ),
                "address": _csv_required_number(
                    row,
                    "address",
                    location,
                    errors,
                    integer=True
                ),
                "count": _csv_required_number(
                    row,
                    "count",
                    location,
                    errors,
                    integer=True
                ),
                "data_type": row.get(
                    "data_type",
                    ""
                ).strip().lower(),
                "scale": _csv_required_number(
                    row,
                    "scale",
                    location,
                    errors
                ),
                "unit": _csv_required_text(
                    row,
                    "unit",
                    location,
                    errors
                )
            }
        )

    return measurements


def _assign_missing_unit_ids(devices, existing_devices, errors):
    """Eksik Unit ID alanlarına kullanılmayan adresleri atar."""

    used_unit_ids = {
        device.get("unit_id")
        for device in existing_devices
        if device.get("unit_id") is not None
    }
    used_unit_ids.update(
        device.get("unit_id")
        for device in devices
        if device.get("unit_id") is not None
    )

    for index, device in enumerate(devices, start=2):
        if device.get("unit_id") is not None:
            continue

        available_unit_id = next(
            (
                unit_id
                for unit_id in range(1, 248)
                if unit_id not in used_unit_ids
            ),
            None
        )

        if available_unit_id is None:
            errors.append(
                f"devices.csv satır {index}: boş Unit ID kalmadı."
            )
            continue

        device["unit_id"] = available_unit_id
        used_unit_ids.add(available_unit_id)


def _prepare_csv_import():
    """CSV dosyalarını okur, cihazlara bağlar ve doğrular."""

    errors = []
    auto_unit_ids = request.form.get(
        "auto_unit_ids",
        "false"
    ).strip().lower() in {
        "true",
        "1",
        "on",
        "evet"
    }
    device_rows = _read_uploaded_csv(
        request.files.get("devices_file"),
        [
            "key",
            "name",
            "protocol",
            "unit_id"
        ],
        "Cihaz CSV",
        errors
    )
    measurement_rows = _read_uploaded_csv(
        request.files.get("measurements_file"),
        [
            "device_key",
            "key",
            "name",
            "function_code",
            "address",
            "count",
            "data_type",
            "scale",
            "unit"
        ],
        "Ölçüm CSV",
        errors
    )
    devices = _parse_devices_csv(
        device_rows,
        errors,
        allow_missing_unit_id=auto_unit_ids
    )
    measurements = _parse_measurements_csv(
        measurement_rows,
        errors
    )
    devices_by_key = {
        device["key"]: device
        for device in devices
        if device["key"]
    }

    for measurement in measurements:
        device = devices_by_key.get(
            measurement["device_key"]
        )

        if device is None:
            errors.append(
                "measurements.csv içinde bulunamayan cihaz key'i: "
                f"'{measurement['device_key']}'."
            )
            continue

        device["measurements"].append(
            {
                key: value
                for key, value in measurement.items()
                if key != "device_key"
            }
        )

    configuration = load_configuration_from_database()
    existing_devices = configuration["devices"]

    if auto_unit_ids:
        _assign_missing_unit_ids(
            devices,
            existing_devices,
            errors
        )

    valid_devices = []

    for index, device in enumerate(devices, start=2):
        try:
            validate_new_device(
                device,
                existing_devices + valid_devices
            )
        except ConfigurationError as error:
            errors.append(
                f"devices.csv satır {index} doğrulanamadı:\n{error}"
            )
            continue

        valid_devices.append(device)

    return devices, measurements, errors


@app.route("/api/devices/import-preview", methods=["POST"])
def api_device_import_preview():
    """CSV dosyalarını kaydetmeden doğrular ve önizleme döndürür."""

    try:
        devices, measurements, errors = _prepare_csv_import()
    except sqlite3.Error as error:
        return jsonify(
            {
                "ok": False,
                "error": "Mevcut cihazlar doğrulama için okunamadı.",
                "detail": str(error)
            }
        ), 500

    if errors:
        return jsonify(
            {
                "ok": False,
                "error": "CSV doğrulaması başarısız.",
                "details": errors
            }
        ), 400

    return jsonify(
        {
            "ok": True,
            "message": "CSV dosyaları kaydetmeden doğrulandı.",
            "device_count": len(devices),
            "measurement_count": len(measurements),
            "devices": [
                {
                    "key": device["key"],
                    "name": device["name"],
                    "protocol": device["protocol"],
                    "unit_id": device["unit_id"],
                    "measurement_count": len(
                        device["measurements"]
                    )
                }
                for device in devices
            ]
        }
    )


@app.route("/api/devices/import", methods=["POST"])
def api_device_import():
    """Doğrulanmış CSV dosyalarını SQLite'a tek transaction ile ekler."""

    try:
        devices, measurements, errors = _prepare_csv_import()
    except sqlite3.Error as error:
        return jsonify(
            {
                "ok": False,
                "error": "Mevcut cihazlar doğrulama için okunamadı.",
                "detail": str(error)
            }
        ), 500

    if errors:
        return jsonify(
            {
                "ok": False,
                "error": "CSV kaydı yapılmadı; doğrulama başarısız.",
                "details": errors
            }
        ), 400

    try:
        device_ids = add_devices_with_measurements_bulk(
            devices
        )
    except sqlite3.IntegrityError as error:
        return jsonify(
            {
                "ok": False,
                "error": "CSV kaydı veritabanı kısıtlarına uymuyor.",
                "detail": str(error)
            }
        ), 409

    return jsonify(
        {
            "ok": True,
            "message": "CSV cihazları ve ölçümleri SQLite'a kaydedildi.",
            "device_count": len(device_ids),
            "measurement_count": len(measurements),
            "device_ids": device_ids
        }
    ), 201


@app.route("/api/devices/import-template/<template_name>")
def api_device_import_template(template_name):
    """Toplu cihaz içe aktarma için boş CSV şablonu indirir."""

    templates = {
        "devices": (
            "modbus_devices_template.csv",
            [
                "key",
                "name",
                "protocol",
                "unit_id",
                "enabled",
                "host",
                "port",
                "transport",
                "serial_port",
                "baudrate",
                "parity",
                "stopbits",
                "bytesize",
                "timeout",
                "retry_count",
                "retry_delay"
            ]
        ),
        "measurements": (
            "modbus_measurements_template.csv",
            [
                "device_key",
                "key",
                "name",
                "function_code",
                "address",
                "count",
                "data_type",
                "scale",
                "unit"
            ]
        )
    }

    template = templates.get(template_name)

    if template is None:
        return jsonify(
            {
                "ok": False,
                "error": "Bilinmeyen CSV şablonu."
            }
        ), 404

    file_name, headers = template
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)

    csv_bytes = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )

    return send_file(
        csv_bytes,
        as_attachment=True,
        download_name=file_name,
        mimetype="text/csv"
    )


@app.route("/api/devices/bulk", methods=["POST"])
def api_add_devices_bulk():
    """Doğrulanmış cihaz listesini tek transaction içinde ekler."""

    payload = request.get_json(
        silent=True
    )

    devices = (
        payload.get("devices")
        if isinstance(payload, dict)
        else None
    )

    if not isinstance(devices, list) or not devices:
        return jsonify(
            {
                "ok": False,
                "error": "devices alanı boş olmayan bir liste olmalı."
            }
        ), 400

    if len(devices) > 1000:
        return jsonify(
            {
                "ok": False,
                "error": "Tek seferde en fazla 1000 cihaz eklenebilir."
            }
        ), 400

    try:
        configuration = load_configuration_from_database()
        existing_devices = configuration["devices"]
        valid_devices = []
        errors = []

        for index, device in enumerate(devices, start=1):
            try:
                validate_new_device(
                    device,
                    existing_devices + valid_devices
                )
            except ConfigurationError as error:
                errors.append(
                    f"{index}. cihaz doğrulanamadı:\n{error}"
                )
                continue

            valid_devices.append(device)

        if errors:
            return jsonify(
                {
                    "ok": False,
                    "error": "Toplu cihaz doğrulaması başarısız.",
                    "details": "\n\n".join(errors)
                }
            ), 400

        device_ids = add_devices_with_measurements_bulk(
            valid_devices
        )
    except sqlite3.IntegrityError as error:
        return jsonify(
            {
                "ok": False,
                "error": "Toplu kayıt veritabanı kısıtlarına uymuyor.",
                "detail": str(error)
            }
        ), 409

    return jsonify(
        {
            "ok": True,
            "message": "Cihazlar ve ölçümleri toplu olarak eklendi.",
            "count": len(device_ids),
            "device_ids": device_ids
        }
    ), 201


@app.route("/api/devices/<device_key>", methods=["PATCH"])
def api_update_device(device_key):
    """Mevcut cihazı ve ölçüm tanımlarını doğrulayarak günceller."""

    device = request.get_json(
        silent=True
    )

    if not isinstance(device, dict):
        return jsonify(
            {
                "ok": False,
                "error": "İstek gövdesi JSON nesnesi olmalı."
            }
        ), 400

    try:
        configuration = load_configuration_from_database()
        existing_devices = configuration["devices"]

        if not any(
            existing_device.get("key") == device_key
            for existing_device in existing_devices
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": "Cihaz bulunamadı."
                }
            ), 404

        validate_updated_device(
            device,
            existing_devices,
            device_key
        )

        updated = update_device_with_measurements(
            device_key,
            device
        )

        if not updated:
            return jsonify(
                {
                    "ok": False,
                    "error": "Cihaz bulunamadı."
                }
            ), 404
    except ConfigurationError as error:
        return jsonify(
            {
                "ok": False,
                "error": str(error)
            }
        ), 400
    except sqlite3.IntegrityError as error:
        return jsonify(
            {
                "ok": False,
                "error": "Cihaz güncellemesi veritabanı kısıtlarına uymuyor.",
                "detail": str(error)
            }
        ), 409

    return jsonify(
        {
            "ok": True,
            "message": "Cihaz başarıyla güncellendi.",
            "device_key": device["key"]
        }
    )


@app.route("/api/devices/<device_key>/status", methods=["PATCH"])
def api_set_device_status(device_key):
    """Bir cihazı etkinleştirir veya polling'den çıkarır."""

    payload = request.get_json(
        silent=True
    )

    if not isinstance(payload, dict) or not isinstance(
        payload.get("enabled"),
        bool
    ):
        return jsonify(
            {
                "ok": False,
                "error": "enabled alanı doğru/yanlış biçiminde olmalı."
            }
        ), 400

    updated = set_device_enabled(
        device_key,
        payload["enabled"]
    )

    if not updated:
        return jsonify(
            {
                "ok": False,
                "error": "Cihaz bulunamadı."
            }
        ), 404

    return jsonify(
        {
            "ok": True,
            "message": (
                "Cihaz etkinleştirildi."
                if payload["enabled"]
                else "Cihaz devre dışı bırakıldı."
            ),
            "device_key": device_key,
            "enabled": payload["enabled"]
        }
    )


@app.route("/api/devices/bulk-action", methods=["POST"])
def api_bulk_device_action():
    """Seçilen cihazlarda etkinlik veya silme işlemini topluca uygular."""

    payload = request.get_json(
        silent=True
    )

    device_keys = (
        payload.get("device_keys")
        if isinstance(payload, dict)
        else None
    )
    action = (
        payload.get("action")
        if isinstance(payload, dict)
        else None
    )

    if (
        not isinstance(device_keys, list)
        or not device_keys
        or len(device_keys) > 1000
        or any(
            not isinstance(device_key, str) or not device_key.strip()
            for device_key in device_keys
        )
    ):
        return jsonify(
            {
                "ok": False,
                "error": "device_keys boş olmayan bir cihaz anahtarı listesi olmalı."
            }
        ), 400

    if action not in {"enable", "disable", "delete"}:
        return jsonify(
            {
                "ok": False,
                "error": "Geçersiz toplu cihaz işlemi."
            }
        ), 400

    normalized_keys = list(
        dict.fromkeys(
            device_key.strip()
            for device_key in device_keys
        )
    )
    configuration = load_configuration_from_database()
    existing_keys = {
        device.get("key")
        for device in configuration["devices"]
    }
    missing_keys = [
        device_key
        for device_key in normalized_keys
        if device_key not in existing_keys
    ]

    if missing_keys:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "Bazı cihazlar bulunamadı: "
                    + ", ".join(missing_keys[:10])
                )
            }
        ), 404

    if action == "delete":
        affected_count = delete_devices(normalized_keys)
        message = f"{affected_count} cihaz ve ölçümleri silindi."
    else:
        enabled = action == "enable"
        affected_count = set_devices_enabled(
            normalized_keys,
            enabled
        )
        message = (
            f"{affected_count} cihaz etkinleştirildi."
            if enabled
            else f"{affected_count} cihaz devre dışı bırakıldı."
        )

    return jsonify(
        {
            "ok": True,
            "action": action,
            "count": affected_count,
            "message": message
        }
    )


@app.route("/api/devices/<device_key>", methods=["DELETE"])
def api_delete_device(device_key):
    """Cihazı ve bağlı ölçüm tanımlarını siler."""

    deleted = delete_device(device_key)

    if not deleted:
        return jsonify(
            {
                "ok": False,
                "error": "Cihaz bulunamadı."
            }
        ), 404

    return jsonify(
        {
            "ok": True,
            "message": "Cihaz ve bağlı ölçümleri silindi.",
            "device_key": device_key
        }
    )


@app.route("/download/csv")
def download_csv():
    device_key = request.args.get(
        "device_key",
        ""
    ).strip()

    measurement_key = request.args.get(
        "measurement_key",
        ""
    ).strip()

    start_date = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date = request.args.get(
        "end_date",
        ""
    ).strip()

    export_fields = [
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

    selected_rows = load_reading_history_from_database(
        device_key=device_key or None,
        measurement_key=measurement_key or None,
        start_date=start_date or None,
        end_date=end_date or None,
        limit=None
    )

    output = io.StringIO(newline="")

    writer = csv.DictWriter(
        output,
        fieldnames=export_fields,
        extrasaction="ignore"
    )

    writer.writeheader()
    writer.writerows(selected_rows)

    csv_bytes = io.BytesIO(
        output.getvalue().encode("utf-8-sig")
    )

    return send_file(
        csv_bytes,
        as_attachment=True,
        download_name="modbus_readings_filtreli.csv",
        mimetype="text/csv"
    )
@app.route("/download/json")
def download_json():
    device_key = request.args.get(
        "device_key",
        ""
    ).strip()

    measurement_key = request.args.get(
        "measurement_key",
        ""
    ).strip()

    start_date = request.args.get(
        "start_date",
        ""
    ).strip()

    end_date = request.args.get(
        "end_date",
        ""
    ).strip()

    selected_rows = load_reading_history_from_database(
        device_key=device_key or None,
        measurement_key=measurement_key or None,
        start_date=start_date or None,
        end_date=end_date or None,
        limit=None
    )

    json_text = json.dumps(
        selected_rows,
        ensure_ascii=False,
        indent=2
    )

    json_bytes = io.BytesIO(
        json_text.encode("utf-8")
    )

    return send_file(
        json_bytes,
        as_attachment=True,
        download_name="modbus_readings_filtreli.json",
        mimetype="application/json"
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
