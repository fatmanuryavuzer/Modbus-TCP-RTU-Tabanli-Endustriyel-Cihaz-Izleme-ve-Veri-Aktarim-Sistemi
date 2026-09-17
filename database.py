"""Modbus Monitor SQLite veritabanı bağlantısı ve tablo tanımları."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path


DATABASE_FILE = Path(__file__).with_name(
    "modbus_monitor.db"
)


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_key TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL,
    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'rtu')),
    enabled INTEGER NOT NULL DEFAULT 1
        CHECK (enabled IN (0, 1)),
    transport TEXT
        CHECK (
            transport IS NULL
            OR transport IN ('memory', 'serial')
        ),
    host TEXT,
    port INTEGER
        CHECK (
            port IS NULL
            OR port BETWEEN 1 AND 65535
        ),
    serial_port TEXT,
    baudrate INTEGER
        CHECK (
            baudrate IS NULL
            OR baudrate > 0
        ),
    parity TEXT
        CHECK (
            parity IS NULL
            OR parity IN ('N', 'E', 'O')
        ),
    stopbits REAL
        CHECK (
            stopbits IS NULL
            OR stopbits IN (1, 1.5, 2)
        ),
    bytesize INTEGER
        CHECK (
            bytesize IS NULL
            OR bytesize BETWEEN 5 AND 8
        ),
    timeout REAL NOT NULL DEFAULT 3
        CHECK (timeout > 0),
    retry_count INTEGER NOT NULL DEFAULT 2
        CHECK (retry_count >= 0),
    retry_delay REAL NOT NULL DEFAULT 0.5
        CHECK (retry_delay >= 0),
    unit_id INTEGER NOT NULL UNIQUE
        CHECK (unit_id BETWEEN 1 AND 247),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    measurement_key TEXT NOT NULL,
    measurement_name TEXT NOT NULL,
    function_code INTEGER NOT NULL DEFAULT 3
        CHECK (function_code = 3),
    address INTEGER NOT NULL
        CHECK (address BETWEEN 0 AND 65535),
    count INTEGER NOT NULL
        CHECK (count BETWEEN 1 AND 125),
    data_type TEXT NOT NULL
        CHECK (data_type IN ('u16', 's16', 'u32')),
    scale REAL NOT NULL,
    unit TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (device_id, measurement_key),
    FOREIGN KEY (device_id)
        REFERENCES devices (id)
        ON DELETE CASCADE,
    CHECK (
        address + count <= 65536
    ),
    CHECK (
        (data_type IN ('u16', 's16') AND count = 1)
        OR (data_type = 'u32' AND count = 2)
    )
);

CREATE TABLE IF NOT EXISTS current_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    device_key TEXT NOT NULL,
    device_name TEXT NOT NULL,
    measurement_key TEXT NOT NULL,
    measurement_name TEXT NOT NULL,
    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'rtu')),
    unit_id INTEGER NOT NULL
        CHECK (unit_id BETWEEN 1 AND 247),
    address INTEGER NOT NULL
        CHECK (address BETWEEN 0 AND 65535),
    count INTEGER NOT NULL
        CHECK (count BETWEEN 1 AND 125),
    data_type TEXT NOT NULL
        CHECK (data_type IN ('u16', 's16', 'u32')),
    raw_value TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('OK', 'HATA')),
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (device_id, measurement_key),
    FOREIGN KEY (device_id)
        REFERENCES devices (id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reading_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    device_key TEXT NOT NULL,
    device_name TEXT NOT NULL,
    measurement_key TEXT NOT NULL,
    measurement_name TEXT NOT NULL,
    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'rtu')),
    unit_id INTEGER NOT NULL
        CHECK (unit_id BETWEEN 1 AND 247),
    address INTEGER NOT NULL
        CHECK (address BETWEEN 0 AND 65535),
    count INTEGER NOT NULL
        CHECK (count BETWEEN 1 AND 125),
    data_type TEXT NOT NULL
        CHECK (data_type IN ('u16', 's16', 'u32')),
    raw_value TEXT,
    value TEXT,
    unit TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('OK', 'HATA')),
    error TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id)
        REFERENCES devices (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reading_history_timestamp
    ON reading_history (timestamp);

CREATE INDEX IF NOT EXISTS idx_reading_history_device
    ON reading_history (device_key, timestamp);

CREATE TABLE IF NOT EXISTS device_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL UNIQUE,
    device_key TEXT NOT NULL,
    device_name TEXT NOT NULL,
    protocol TEXT NOT NULL
        CHECK (protocol IN ('tcp', 'rtu')),
    unit_id INTEGER NOT NULL
        CHECK (unit_id BETWEEN 1 AND 247),
    status TEXT NOT NULL
        CHECK (
            status IN (
                'ONLINE',
                'OFFLINE',
                'DEGRADED',
                'UNKNOWN',
                'DISABLED'
            )
        ),
    total_measurements INTEGER NOT NULL
        CHECK (total_measurements >= 0),
    successful_measurements INTEGER NOT NULL
        CHECK (successful_measurements >= 0),
    failed_measurements INTEGER NOT NULL
        CHECK (failed_measurements >= 0),
    consecutive_error_cycles INTEGER NOT NULL
        CHECK (consecutive_error_cycles >= 0),
    last_successful_reading TEXT,
    last_error TEXT,
    last_error_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (device_id)
        REFERENCES devices (id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS simulation_settings (
    settings_id INTEGER PRIMARY KEY
        CHECK (settings_id = 1),
    rtu_enabled INTEGER NOT NULL DEFAULT 0
        CHECK (rtu_enabled IN (0, 1)),
    serial_port TEXT NOT NULL DEFAULT '',
    baudrate INTEGER NOT NULL DEFAULT 9600
        CHECK (baudrate > 0),
    parity TEXT NOT NULL DEFAULT 'N'
        CHECK (parity IN ('N', 'E', 'O')),
    stopbits REAL NOT NULL DEFAULT 1
        CHECK (stopbits IN (1, 1.5, 2)),
    bytesize INTEGER NOT NULL DEFAULT 8
        CHECK (bytesize BETWEEN 5 AND 8),
    timeout REAL NOT NULL DEFAULT 1
        CHECK (timeout > 0)
);

CREATE TABLE IF NOT EXISTS transfer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    method TEXT NOT NULL
        CHECK (method IN ('ftp', 'sftp', 'json-api')),
    file_format TEXT NOT NULL
        CHECK (file_format IN ('csv', 'json')),
    transfer_window TEXT NOT NULL
        CHECK (transfer_window IN ('manual', 'custom')),
    window_hours INTEGER
        CHECK (window_hours IS NULL OR window_hours BETWEEN 1 AND 24),
    record_count INTEGER NOT NULL
        CHECK (record_count >= 0),
    content_size INTEGER NOT NULL
        CHECK (content_size >= 0),
    local_path TEXT NOT NULL,
    destination TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL
        CHECK (status IN ('PREPARED', 'SUCCESS', 'FAILED')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_transfer_history_created_at
    ON transfer_history (created_at);
"""


def get_connection():
    """Veritabanına bağlanır ve satırları sözlük gibi döndürür."""

    connection = sqlite3.connect(
        DATABASE_FILE
    )
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


@contextmanager
def managed_connection():
    """Bağlantıyı transaction sonunda kapatan güvenli yardımcıdır."""

    connection = get_connection()

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def create_tables():
    """Gerekli tabloları ve varsayılan simülasyon ayarını oluşturur."""

    with managed_connection() as connection:
        connection.executescript(
            CREATE_TABLES_SQL
        )

        _migrate_transfer_history(connection)

        existing_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(devices)"
            ).fetchall()
        }

        if "enabled" not in existing_columns:
            connection.execute(
                """
                ALTER TABLE devices
                ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1
                CHECK (enabled IN (0, 1))
                """
            )

        transfer_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(transfer_history)"
            ).fetchall()
        }

        if "filters_json" not in transfer_columns:
            connection.execute(
                """
                ALTER TABLE transfer_history
                ADD COLUMN filters_json TEXT NOT NULL DEFAULT '{}'
                """
            )

        connection.execute(
            """
            INSERT OR IGNORE INTO simulation_settings (
                settings_id
            )
            VALUES (1)
            """
        )
        connection.commit()


def _migrate_transfer_history(connection):
    """Eski 1/3 saatlik aktarım geçmişini yeni yapıya taşır.

    SQLite mevcut bir tablonun CHECK kuralını doğrudan değiştiremediği için
    eski tablo güvenli biçimde yeni tabloya kopyalanır. Eski 1h ve 3h kayıtları
    custom + ilgili saat değeri olarak korunur.
    """

    table_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'transfer_history'
        """
    ).fetchone()

    if not table_row:
        return

    table_sql = (
        table_row["sql"] or ""
    ).lower()

    if (
        "window_hours" in table_sql
        and "'custom'" in table_sql
    ):
        return

    connection.execute(
        """
        CREATE TABLE transfer_history_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            method TEXT NOT NULL
                CHECK (method IN ('ftp', 'sftp', 'json-api')),
            file_format TEXT NOT NULL
                CHECK (file_format IN ('csv', 'json')),
            transfer_window TEXT NOT NULL
                CHECK (transfer_window IN ('manual', 'custom')),
            window_hours INTEGER
                CHECK (
                    window_hours IS NULL
                    OR window_hours BETWEEN 1 AND 24
                ),
            record_count INTEGER NOT NULL
                CHECK (record_count >= 0),
            content_size INTEGER NOT NULL
                CHECK (content_size >= 0),
            local_path TEXT NOT NULL,
            destination TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL
                CHECK (status IN ('PREPARED', 'SUCCESS', 'FAILED')),
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
        """
    )

    connection.execute(
        """
        INSERT INTO transfer_history_new (
            id,
            file_name,
            method,
            file_format,
            transfer_window,
            window_hours,
            record_count,
            content_size,
            local_path,
            destination,
            filters_json,
            status,
            error,
            created_at,
            completed_at
        )
        SELECT
            id,
            file_name,
            method,
            file_format,
            CASE
                WHEN transfer_window IN ('1h', '3h')
                    THEN 'custom'
                ELSE 'manual'
            END,
            CASE
                WHEN transfer_window = '1h' THEN 1
                WHEN transfer_window = '3h' THEN 3
                ELSE NULL
            END,
            record_count,
            content_size,
            local_path,
            destination,
            '{}',
            status,
            error,
            created_at,
            completed_at
        FROM transfer_history
        """
    )

    connection.execute(
        "DROP TABLE transfer_history"
    )

    connection.execute(
        "ALTER TABLE transfer_history_new RENAME TO transfer_history"
    )

    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_transfer_history_created_at
            ON transfer_history (created_at)
        """
    )


def create_transfer_history(
    file_name,
    method,
    file_format,
    transfer_window,
    window_hours,
    record_count,
    content_size,
    local_path,
    destination,
    filters=None
):
    """Aktarımın başlangıcını SQLite'ta kayıt altına alır."""

    create_tables()

    with managed_connection() as connection:
        filters_json = json.dumps(
            filters or {},
            ensure_ascii=False
        )

        cursor = connection.execute(
            """
            INSERT INTO transfer_history (
                file_name,
                method,
                file_format,
                transfer_window,
                window_hours,
                record_count,
                content_size,
                local_path,
                destination,
                filters_json,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED')
            """,
            (
                file_name,
                method,
                file_format,
                transfer_window,
                window_hours,
                record_count,
                content_size,
                local_path,
                destination,
                filters_json
            )
        )

        return cursor.lastrowid


def update_transfer_history(
    transfer_id,
    status,
    error=None
):
    """Aktarımın başarılı veya hatalı sonucunu günceller."""

    if status not in {
        "SUCCESS",
        "FAILED"
    }:
        raise ValueError(
            "Geçersiz aktarım geçmişi durumu."
        )

    create_tables()

    with managed_connection() as connection:
        connection.execute(
            """
            UPDATE transfer_history
            SET status = ?,
                error = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, error, transfer_id)
        )


def load_expired_successful_transfer_files(
    retention_days=7
):
    """Yedi günden eski başarılı aktarım dosyalarını listeler."""

    try:
        retention_days = int(
            retention_days
        )
    except (TypeError, ValueError):
        retention_days = 7

    retention_days = max(
        1,
        retention_days
    )

    cutoff = (
        datetime.now()
        - timedelta(days=retention_days)
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    create_tables()

    with managed_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, local_path
            FROM transfer_history
            WHERE status = 'SUCCESS'
              AND created_at < ?
            ORDER BY id
            """,
            (cutoff,)
        ).fetchall()

    return [
        {
            "id": row["id"],
            "local_path": row["local_path"]
        }
        for row in rows
    ]


def load_transfer_history(
    limit=20
):
    """Aktarım geçmişinin son kayıtlarını kullanıcı arayüzü için yükler."""

    try:
        limit = int(
            limit
        )
    except (TypeError, ValueError):
        limit = 20

    limit = max(
        1,
        min(limit, 100)
    )

    create_tables()

    with managed_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                file_name,
                method,
                file_format,
                transfer_window,
                window_hours,
                record_count,
                content_size,
                destination,
                filters_json,
                status,
                error,
                created_at,
                completed_at
            FROM transfer_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    records = []

    for row in rows:
        record = dict(row)
        try:
            record["filters"] = json.loads(
                record.pop(
                    "filters_json",
                    "{}"
                ) or "{}"
            )
        except json.JSONDecodeError:
            record["filters"] = {}

        records.append(record)

    return records


def _insert_device_with_connection(connection, device):
    """Açık bağlantı içinde tek cihazı ve ölçümlerini ekler."""

    protocol = device["protocol"]
    is_tcp = protocol == "tcp"
    is_rtu = protocol == "rtu"

    cursor = connection.execute(
        """
        INSERT INTO devices (
            device_key,
            device_name,
            protocol,
            enabled,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device["key"],
            device["name"],
            protocol,
            int(device.get("enabled", True)),
            device.get("transport") if is_rtu else None,
            device.get("host") if is_tcp else None,
            device.get("port") if is_tcp else None,
            device.get("serial_port") if is_rtu else None,
            device.get("baudrate") if is_rtu else None,
            device.get("parity") if is_rtu else None,
            device.get("stopbits") if is_rtu else None,
            device.get("bytesize") if is_rtu else None,
            device.get("timeout", 3),
            device.get("retry_count", 2),
            device.get("retry_delay", 0.5),
            device["unit_id"]
        )
    )

    device_id = cursor.lastrowid

    for measurement in device["measurements"]:
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

    return device_id


def add_device_with_measurements(device):
    """Bir cihazı ve bağlı ölçümlerini tek transaction içinde ekler."""

    create_tables()
    connection = get_connection()

    try:
        with connection:
            device_id = _insert_device_with_connection(
                connection,
                device
            )

        return device_id
    finally:
        connection.close()


def add_devices_with_measurements_bulk(devices):
    """Birden fazla cihazı tek transaction içinde toplu ekler."""

    create_tables()
    connection = get_connection()

    try:
        with connection:
            device_ids = [
                _insert_device_with_connection(
                    connection,
                    device
                )
                for device in devices
            ]

        return device_ids
    finally:
        connection.close()


def update_device_with_measurements(device_key, device):
    """Bir cihazı ve tüm ölçüm tanımlarını tek transaction içinde günceller."""

    create_tables()

    protocol = device["protocol"]
    is_tcp = protocol == "tcp"
    is_rtu = protocol == "rtu"

    connection = get_connection()

    try:
        with connection:
            existing_row = connection.execute(
                """
                SELECT id, enabled
                FROM devices
                WHERE device_key = ?
                """,
                (device_key,)
            ).fetchone()

            if existing_row is None:
                return False

            enabled = device.get(
                "enabled",
                bool(existing_row["enabled"])
            )

            connection.execute(
                """
                UPDATE devices
                SET device_key = ?,
                    device_name = ?,
                    protocol = ?,
                    enabled = ?,
                    transport = ?,
                    host = ?,
                    port = ?,
                    serial_port = ?,
                    baudrate = ?,
                    parity = ?,
                    stopbits = ?,
                    bytesize = ?,
                    timeout = ?,
                    retry_count = ?,
                    retry_delay = ?,
                    unit_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    device["key"],
                    device["name"],
                    protocol,
                    int(enabled),
                    device.get("transport") if is_rtu else None,
                    device.get("host") if is_tcp else None,
                    device.get("port") if is_tcp else None,
                    device.get("serial_port") if is_rtu else None,
                    device.get("baudrate") if is_rtu else None,
                    device.get("parity") if is_rtu else None,
                    device.get("stopbits") if is_rtu else None,
                    device.get("bytesize") if is_rtu else None,
                    device.get("timeout", 3),
                    device.get("retry_count", 2),
                    device.get("retry_delay", 0.5),
                    device["unit_id"],
                    existing_row["id"]
                )
            )

            connection.execute(
                """
                DELETE FROM measurements
                WHERE device_id = ?
                """,
                (existing_row["id"],)
            )

            for measurement in device["measurements"]:
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
                        existing_row["id"],
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

        return True
    finally:
        connection.close()


def update_measurement_register(
    device_key,
    measurement_key,
    address,
    count
):
    """Bir ölçümün register adresi ve adetini güvenli şekilde günceller."""

    create_tables()

    with managed_connection() as connection:
        measurement_row = connection.execute(
            """
            SELECT
                measurements.id,
                measurements.device_id,
                measurements.data_type
            FROM measurements
            INNER JOIN devices
                ON devices.id = measurements.device_id
            WHERE devices.device_key = ?
                AND measurements.measurement_key = ?
            """,
            (device_key, measurement_key)
        ).fetchone()

        if measurement_row is None:
            return {
                "ok": False,
                "status_code": 404,
                "error": "Ölçüm bulunamadı."
            }

        required_count = (
            2
            if measurement_row["data_type"] == "u32"
            else 1
        )

        if count != required_count:
            return {
                "ok": False,
                "status_code": 400,
                "error": (
                    f"{measurement_row['data_type'].upper()} veri tipi "
                    f"için register adedi {required_count} olmalı."
                )
            }

        conflicting_row = connection.execute(
            """
            SELECT measurement_key
            FROM measurements
            WHERE device_id = ?
                AND id <> ?
                AND address < ?
                AND address + count > ?
            LIMIT 1
            """,
            (
                measurement_row["device_id"],
                measurement_row["id"],
                address + count,
                address
            )
        ).fetchone()

        if conflicting_row is not None:
            return {
                "ok": False,
                "status_code": 400,
                "error": (
                    "Register aralığı başka bir ölçümle çakışıyor: "
                    f"{conflicting_row['measurement_key']}"
                )
            }

        connection.execute(
            """
            UPDATE measurements
            SET address = ?,
                count = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                address,
                count,
                measurement_row["id"]
            )
        )

        # Yeni register'dan ilk okuma gelene kadar eski değerin
        # yanlış register'a aitmiş gibi gösterilmesini engeller.
        connection.execute(
            """
            UPDATE current_readings
            SET address = ?,
                count = ?,
                status = 'HATA',
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE device_id = ?
                AND measurement_key = ?
            """,
            (
                address,
                count,
                "Yeni register tanımından ilk okuma bekleniyor.",
                measurement_row["device_id"],
                measurement_key
            )
        )

    return {
        "ok": True
    }


def _serialize_reading_value(value):
    """Sayı veya liste biçimindeki ölçüm değerini SQLite metnine çevirir."""

    return json.dumps(
        value,
        ensure_ascii=False
    )


def _deserialize_reading_value(value):
    """SQLite'taki metin değerini tekrar sayı veya listeye çevirir."""

    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _load_device_id_map(connection):
    """device_key değerlerini SQLite cihaz id değerlerine eşler."""

    rows = connection.execute(
        """
        SELECT id, device_key
        FROM devices
        """
    ).fetchall()

    return {
        row["device_key"]: row["id"]
        for row in rows
    }


def replace_current_readings(readings):
    """Son okuma turunu current_readings tablosuna yazar."""

    create_tables()

    with managed_connection() as connection:
        device_ids = _load_device_id_map(connection)

        connection.execute(
            "DELETE FROM current_readings"
        )

        for reading in readings:
            device_key = reading.get("device_key")
            device_id = device_ids.get(device_key)

            if device_id is None:
                raise ValueError(
                    f"Okuma için cihaz bulunamadı: {device_key}"
                )

            connection.execute(
                """
                INSERT INTO current_readings (
                    device_id,
                    device_key,
                    device_name,
                    measurement_key,
                    measurement_name,
                    protocol,
                    unit_id,
                    address,
                    count,
                    data_type,
                    raw_value,
                    value,
                    unit,
                    timestamp,
                    status,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    device_key,
                    reading.get("device_name", ""),
                    reading.get("measurement_key", ""),
                    reading.get("measurement_name", ""),
                    reading.get("protocol", "tcp"),
                    reading.get("unit_id"),
                    reading.get("address"),
                    reading.get("count"),
                    reading.get("data_type", "u16"),
                    _serialize_reading_value(
                        reading.get("raw_value")
                    ),
                    _serialize_reading_value(
                        reading.get("value")
                    ),
                    reading.get("unit", ""),
                    reading.get("timestamp", ""),
                    reading.get("status", "HATA"),
                    reading.get("error")
                )
            )


def append_reading_history(readings):
    """Okuma turunu reading_history tablosuna geçmiş kayıt olarak ekler."""

    if not readings:
        return

    create_tables()

    with managed_connection() as connection:
        device_ids = _load_device_id_map(connection)
        history_rows = []

        for reading in readings:
            device_key = reading.get("device_key")
            device_id = device_ids.get(device_key)

            if device_id is None:
                raise ValueError(
                    f"Geçmiş kayıt için cihaz bulunamadı: {device_key}"
                )

            history_rows.append(
                (
                    device_id,
                    device_key,
                    reading.get("device_name", ""),
                    reading.get("measurement_key", ""),
                    reading.get("measurement_name", ""),
                    reading.get("protocol", "tcp"),
                    reading.get("unit_id"),
                    reading.get("address"),
                    reading.get("count"),
                    reading.get("data_type", "u16"),
                    _serialize_reading_value(
                        reading.get("raw_value")
                    ),
                    _serialize_reading_value(
                        reading.get("value")
                    ),
                    reading.get("unit", ""),
                    reading.get("timestamp", ""),
                    reading.get("status", "HATA"),
                    reading.get("error")
                )
            )

        connection.executemany(
            """
            INSERT INTO reading_history (
                device_id,
                device_key,
                device_name,
                measurement_key,
                measurement_name,
                protocol,
                unit_id,
                address,
                count,
                data_type,
                raw_value,
                value,
                unit,
                timestamp,
                status,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            history_rows
        )


def load_reading_history_from_database(
    device_key=None,
    measurement_key=None,
    start_date=None,
    end_date=None,
    start_timestamp=None,
    end_timestamp=None,
    limit=100
):
    """
    Geçmiş ölçümleri SQLite'tan filtreleyerek okur.
    """

    create_tables()

    conditions = []
    parameters = []

    if device_key:
        conditions.append(
            "device_key = ?"
        )
        parameters.append(
            device_key
        )

    if measurement_key:
        conditions.append(
            "measurement_key = ?"
        )
        parameters.append(
            measurement_key
        )

    if start_date:
        conditions.append(
            "timestamp >= ?"
        )
        parameters.append(
            f"{start_date}T00:00:00"
        )

    if end_date:
        conditions.append(
            "timestamp <= ?"
        )
        parameters.append(
            f"{end_date}T23:59:59"
        )

    if start_timestamp:
        conditions.append(
            "timestamp >= ?"
        )
        parameters.append(
            start_timestamp
        )

    if end_timestamp:
        conditions.append(
            "timestamp <= ?"
        )
        parameters.append(
            end_timestamp
        )

    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 100

        limit = max(
            1,
            min(limit, 1000)
        )

    query = """
        SELECT
            id,
            device_key,
            device_name,
            measurement_key,
            measurement_name,
            protocol,
            unit_id,
            address,
            count,
            data_type,
            raw_value,
            value,
            unit,
            timestamp,
            status,
            error,
            recorded_at
        FROM reading_history
    """

    if conditions:
        query += (
            " WHERE "
            + " AND ".join(conditions)
        )

    query += " ORDER BY timestamp DESC, id DESC"

    if limit is not None:
        query += " LIMIT ?"
        parameters.append(
            limit
        )

    with managed_connection() as connection:
        rows = connection.execute(
            query,
            parameters
        ).fetchall()

    return [
        {
            "id": row["id"],
            "device_key": row["device_key"],
            "device_name": row["device_name"],
            "measurement_key": row["measurement_key"],
            "measurement_name": row["measurement_name"],
            "protocol": row["protocol"],
            "unit_id": row["unit_id"],
            "address": row["address"],
            "count": row["count"],
            "data_type": row["data_type"],
            "raw_value": _deserialize_reading_value(
                row["raw_value"]
            ),
            "value": _deserialize_reading_value(
                row["value"]
            ),
            "unit": row["unit"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "error": row["error"],
            "recorded_at": row["recorded_at"]
        }
        for row in rows
    ]


def count_reading_history_older_than(
    retention_days=30
):
    """Saklama süresini aşan okuma kaydı sayısını hesaplar."""

    try:
        retention_days = int(
            retention_days
        )
    except (TypeError, ValueError):
        retention_days = 30

    retention_days = max(
        1,
        retention_days
    )

    cutoff = (
        datetime.now()
        - timedelta(days=retention_days)
    ).isoformat(
        timespec="seconds"
    )

    create_tables()

    with managed_connection() as connection:
        return connection.execute(
            """
            SELECT COUNT(*)
            FROM reading_history
            WHERE timestamp < ?
            """,
            (cutoff,)
        ).fetchone()[0]


def delete_reading_history_older_than(
    retention_days=30
):
    """Saklama süresini aşan yalnızca okuma geçmişi kayıtlarını siler."""

    try:
        retention_days = int(
            retention_days
        )
    except (TypeError, ValueError):
        retention_days = 30

    retention_days = max(
        1,
        retention_days
    )

    cutoff = (
        datetime.now()
        - timedelta(days=retention_days)
    ).isoformat(
        timespec="seconds"
    )

    create_tables()

    with managed_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM reading_history
            WHERE timestamp < ?
            """,
            (cutoff,)
        )

        return cursor.rowcount


def load_current_readings_from_database():
    """Son ölçüm turunu SQLite'tan arayüz biçiminde döndürür."""

    create_tables()

    with managed_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                device_key,
                device_name,
                measurement_key,
                measurement_name,
                protocol,
                unit_id,
                address,
                count,
                data_type,
                raw_value,
                value,
                unit,
                timestamp,
                status,
                error
            FROM current_readings
            ORDER BY id
            """
        ).fetchall()

    return [
        {
            "device_key": row["device_key"],
            "device_name": row["device_name"],
            "measurement_key": row["measurement_key"],
            "measurement_name": row["measurement_name"],
            "protocol": row["protocol"],
            "unit_id": row["unit_id"],
            "address": row["address"],
            "count": row["count"],
            "data_type": row["data_type"],
            "raw_value": _deserialize_reading_value(
                row["raw_value"]
            ),
            "value": _deserialize_reading_value(
                row["value"]
            ),
            "unit": row["unit"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "error": row["error"]
        }
        for row in rows
    ]


def replace_device_health(devices, health_by_device):
    """Cihaz sağlık kayıtlarını device_health tablosuna yazar."""

    create_tables()

    with managed_connection() as connection:
        device_ids = _load_device_id_map(connection)

        connection.execute(
            "DELETE FROM device_health"
        )

        for device in devices:
            device_key = device.get("key")
            device_id = device_ids.get(device_key)
            health = health_by_device.get(device_key)

            if device_id is None or health is None:
                continue

            connection.execute(
                """
                INSERT INTO device_health (
                    device_id,
                    device_key,
                    device_name,
                    protocol,
                    unit_id,
                    status,
                    total_measurements,
                    successful_measurements,
                    failed_measurements,
                    consecutive_error_cycles,
                    last_successful_reading,
                    last_error,
                    last_error_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    health.get("device_key", device_key),
                    health.get(
                        "device_name",
                        device.get("name", "")
                    ),
                    health.get(
                        "protocol",
                        device.get("protocol", "tcp")
                    ),
                    health.get(
                        "unit_id",
                        device.get("unit_id")
                    ),
                    health.get("status", "UNKNOWN"),
                    health.get("total_measurements", 0),
                    health.get("successful_measurements", 0),
                    health.get("failed_measurements", 0),
                    health.get("consecutive_error_cycles", 0),
                    health.get("last_successful_reading"),
                    health.get("last_error"),
                    health.get("last_error_at"),
                    health.get("updated_at", "")
                )
            )


def load_device_health_from_database():
    """Cihaz sağlık kayıtlarını SQLite'tan liste olarak döndürür."""

    create_tables()

    with managed_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                device_key,
                device_name,
                protocol,
                unit_id,
                status,
                total_measurements,
                successful_measurements,
                failed_measurements,
                consecutive_error_cycles,
                last_successful_reading,
                last_error,
                last_error_at,
                updated_at
            FROM device_health
            ORDER BY device_id
            """
        ).fetchall()

    return [
        {
            "device_key": row["device_key"],
            "device_name": row["device_name"],
            "protocol": row["protocol"],
            "unit_id": row["unit_id"],
            "status": row["status"],
            "total_measurements": row["total_measurements"],
            "successful_measurements": row[
                "successful_measurements"
            ],
            "failed_measurements": row["failed_measurements"],
            "consecutive_error_cycles": row[
                "consecutive_error_cycles"
            ],
            "last_successful_reading": row[
                "last_successful_reading"
            ],
            "last_error": row["last_error"],
            "last_error_at": row["last_error_at"],
            "updated_at": row["updated_at"]
        }
        for row in rows
    ]


def load_configuration_from_database():
    """SQLite kayıtlarını polling'in beklediği ayar yapısına dönüştürür."""

    create_tables()

    with managed_connection() as connection:
        simulation_row = connection.execute(
            """
            SELECT
                rtu_enabled,
                serial_port,
                baudrate,
                parity,
                stopbits,
                bytesize,
                timeout
            FROM simulation_settings
            WHERE settings_id = 1
            """
        ).fetchone()

        if simulation_row is None:
            raise ValueError(
                "simulation_settings tablosunda ayar bulunamadı."
            )

        device_rows = connection.execute(
            """
            SELECT *
            FROM devices
            ORDER BY id
            """
        ).fetchall()

        if not device_rows:
            raise ValueError(
                "SQLite veritabanında hiç cihaz bulunamadı."
            )

        configuration = {
            "simulation": {
                "rtu_enabled": bool(
                    simulation_row["rtu_enabled"]
                ),
                "serial_port": simulation_row["serial_port"],
                "baudrate": simulation_row["baudrate"],
                "parity": simulation_row["parity"],
                "stopbits": simulation_row["stopbits"],
                "bytesize": simulation_row["bytesize"],
                "timeout": simulation_row["timeout"]
            },
            "devices": []
        }

        for device_row in device_rows:
            device = {
                "key": device_row["device_key"],
                "name": device_row["device_name"],
                "protocol": device_row["protocol"],
                "enabled": bool(device_row["enabled"]),
                "unit_id": device_row["unit_id"],
                "timeout": device_row["timeout"],
                "retry_count": device_row["retry_count"],
                "retry_delay": device_row["retry_delay"],
                "measurements": []
            }

            optional_device_fields = (
                "transport",
                "host",
                "port",
                "serial_port",
                "baudrate",
                "parity",
                "stopbits",
                "bytesize"
            )

            for field_name in optional_device_fields:
                field_value = device_row[field_name]

                if field_value is not None:
                    device[field_name] = field_value

            measurement_rows = connection.execute(
                """
                SELECT
                    measurement_key,
                    measurement_name,
                    function_code,
                    address,
                    count,
                    data_type,
                    scale,
                    unit
                FROM measurements
                WHERE device_id = ?
                ORDER BY id
                """,
                (device_row["id"],)
            ).fetchall()

            for measurement_row in measurement_rows:
                device["measurements"].append(
                    {
                        "key": measurement_row[
                            "measurement_key"
                        ],
                        "name": measurement_row[
                            "measurement_name"
                        ],
                        "function_code": measurement_row[
                            "function_code"
                        ],
                        "address": measurement_row["address"],
                        "count": measurement_row["count"],
                        "data_type": measurement_row[
                            "data_type"
                        ],
                        "scale": measurement_row["scale"],
                        "unit": measurement_row["unit"]
                    }
                )

            configuration["devices"].append(
                device
            )

    return configuration


def set_device_enabled(device_key, enabled):
    """Bir cihazın polling'e dahil edilip edilmeyeceğini değiştirir."""

    create_tables()

    with managed_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE devices
            SET enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE device_key = ?
            """,
            (int(enabled), device_key)
        )

        return cursor.rowcount == 1


def set_devices_enabled(device_keys, enabled):
    """Birden fazla cihazın etkinlik durumunu tek transaction ile değiştirir."""

    create_tables()
    normalized_keys = list(dict.fromkeys(device_keys))
    updated_count = 0

    with managed_connection() as connection:
        for start in range(0, len(normalized_keys), 900):
            key_batch = normalized_keys[start:start + 900]
            placeholders = ", ".join("?" for _ in key_batch)
            cursor = connection.execute(
                f"""
                UPDATE devices
                SET enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE device_key IN ({placeholders})
                """,
                [int(enabled), *key_batch]
            )
            updated_count += cursor.rowcount

    return updated_count


def delete_device(device_key):
    """Bir cihazı ve bağlı ölçüm tanımlarını siler."""

    create_tables()

    with managed_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM devices
            WHERE device_key = ?
            """,
            (device_key,)
        )

        return cursor.rowcount == 1


def delete_devices(device_keys):
    """Birden fazla cihazı ve bağlı ölçümlerini tek transaction ile siler."""

    create_tables()
    normalized_keys = list(dict.fromkeys(device_keys))
    deleted_count = 0

    with managed_connection() as connection:
        for start in range(0, len(normalized_keys), 900):
            key_batch = normalized_keys[start:start + 900]
            placeholders = ", ".join("?" for _ in key_batch)
            cursor = connection.execute(
                f"""
                DELETE FROM devices
                WHERE device_key IN ({placeholders})
                """,
                key_batch
            )
            deleted_count += cursor.rowcount

    return deleted_count


def main():
    """Veritabanını komut satırından hazırlar."""

    create_tables()
    print(
        f"SQLite veritabanı hazır: {DATABASE_FILE}"
    )

    with managed_connection() as connection:
        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        ).fetchall()

    print("Oluşturulan tablolar:")

    for row in table_rows:
        print(f"- {row['name']}")


if __name__ == "__main__":
    main()
