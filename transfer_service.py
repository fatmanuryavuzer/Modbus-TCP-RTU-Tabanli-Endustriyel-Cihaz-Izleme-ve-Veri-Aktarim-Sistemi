import csv
import io
import json
import paramiko
from datetime import datetime
from ftplib import FTP
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


CSV_EXPORT_FIELDS = [
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


TRANSFER_OUTBOX_DIR = Path(__file__).with_name(
    "transfer_outbox"
)

TRANSFER_WINDOW_DIRECTORIES = {
    "manual": "manuel",
    "custom": "gecici"
}


def ensure_transfer_directories():
    """Aktarım dosyaları için gerekli klasörleri hazırlar."""

    for directory_name in TRANSFER_WINDOW_DIRECTORIES.values():
        (TRANSFER_OUTBOX_DIR / directory_name).mkdir(
            parents=True,
            exist_ok=True
        )


def save_transfer_file(
    content_bytes,
    file_name,
    window="manual"
):
    """Aktarım dosyasını yerel outbox klasörüne kaydeder.

    window değerleri:
        manual: Arayüzden elle başlatılan gönderim
        custom: Kullanıcının seçtiği saat aralığı
    """

    normalized_window = str(
        window or "manual"
    ).lower()

    if normalized_window not in TRANSFER_WINDOW_DIRECTORIES:
        raise ValueError(
            "Geçersiz aktarım zaman aralığı."
        )

    ensure_transfer_directories()

    target_directory = (
        TRANSFER_OUTBOX_DIR
        / TRANSFER_WINDOW_DIRECTORIES[normalized_window]
    )

    target_path = target_directory / Path(file_name).name
    duplicate_number = 2

    while target_path.exists():
        target_path = target_directory / (
            f"{Path(file_name).stem}_{duplicate_number}"
            f"{Path(file_name).suffix}"
        )
        duplicate_number += 1

    target_path.write_bytes(
        content_bytes
    )

    return {
        "file_name": target_path.name,
        "window": normalized_window,
        "directory": str(
            target_path.parent.relative_to(
                TRANSFER_OUTBOX_DIR.parent
            )
        ),
        "path": str(target_path)
    }


def cleanup_expired_successful_transfer_files(
    expired_files
):
    """Süresi dolan başarılı dosyaları güvenli biçimde temizler."""

    outbox_root = TRANSFER_OUTBOX_DIR.resolve()
    deleted_files = []

    for file_record in expired_files:
        candidate = Path(
            file_record.get(
                "local_path",
                ""
            )
        ).resolve()

        try:
            candidate.relative_to(
                outbox_root
            )
        except ValueError:
            continue

        if candidate.is_file():
            candidate.unlink()
            deleted_files.append(
                str(candidate)
            )

    return deleted_files


def delete_transfer_file(
    file_record
):
    """Başarılı aktarımın geçici dosyasını güvenli biçimde siler.

    Yalnızca transfer_outbox klasörünün içindeki bir dosya silinebilir.
    Böylece veritabanındaki hatalı veya değiştirilmiş bir yol, proje dışındaki
    bir dosyanın silinmesine neden olmaz.
    """

    if not isinstance(
        file_record,
        dict
    ):
        return False

    candidate = Path(
        file_record.get(
            "path",
            ""
        )
    ).resolve()

    outbox_root = TRANSFER_OUTBOX_DIR.resolve()

    try:
        candidate.relative_to(
            outbox_root
        )
    except ValueError:
        return False

    if not candidate.is_file():
        return False

    candidate.unlink()
    return True


def build_transfer_content(
    readings,
    file_format
):
    """
    Ölçüm kayıtlarını CSV veya JSON dosya içeriğine çevirir.

    Geri dönüş:
        content_bytes: Dosya içeriği
        file_name: Önerilen dosya adı
        mime_type: Dosya türü
    """

    normalized_format = str(
        file_format or ""
    ).lower()

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    if normalized_format == "json":
        json_text = json.dumps(
            readings,
            ensure_ascii=False,
            indent=2
        )

        content_bytes = json_text.encode(
            "utf-8"
        )

        file_name = (
            f"modbus_readings_{timestamp}.json"
        )

        mime_type = "application/json"

        return (
            content_bytes,
            file_name,
            mime_type
        )

    if normalized_format == "csv":
        output = io.StringIO(
            newline=""
        )

        writer = csv.DictWriter(
            output,
            fieldnames=CSV_EXPORT_FIELDS,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(readings)

        content_bytes = output.getvalue().encode(
            "utf-8-sig"
        )

        file_name = (
            f"modbus_readings_{timestamp}.csv"
        )

        mime_type = "text/csv"

        return (
            content_bytes,
            file_name,
            mime_type
        )

    raise ValueError(
        "Desteklenmeyen dosya formatı."
    )


def send_via_ftp(
    content_bytes,
    file_name,
    destination,
    username,
    password,
    timeout=15
):
    """Hazırlanan dosya içeriğini FTP sunucusuna gönderir."""

    parsed_url = urlparse(
        destination
    )

    if parsed_url.scheme.lower() != "ftp":
        raise ValueError(
            "FTP hedef adresi ftp:// ile başlamalıdır."
        )

    if not parsed_url.hostname:
        raise ValueError(
            "FTP hedef adresinde sunucu adı bulunamadı."
        )

    remote_directory = unquote(
        parsed_url.path or ""
    )

    ftp = FTP()

    try:
        ftp.connect(
            host=parsed_url.hostname,
            port=parsed_url.port or 21,
            timeout=timeout
        )

        ftp.login(
            user=username,
            passwd=password
        )

        if remote_directory:
            ftp.cwd(
                remote_directory
            )

        file_stream = io.BytesIO(
            content_bytes
        )

        try:
            ftp.storbinary(
                f"STOR {file_name}",
                file_stream
            )
        finally:
            file_stream.close()

        return {
            "file_name": file_name,
            "server": parsed_url.hostname,
            "directory": remote_directory or "/"
        }

    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def send_via_sftp(
    content_bytes,
    file_name,
    destination,
    username,
    password,
    timeout=15
):
    """Hazırlanan dosya içeriğini SFTP sunucusuna gönderir."""

    parsed_url = urlparse(
        destination
    )

    if parsed_url.scheme.lower() != "sftp":
        raise ValueError(
            "SFTP hedef adresi sftp:// ile başlamalıdır."
        )

    if not parsed_url.hostname:
        raise ValueError(
            "SFTP hedef adresinde sunucu adı bulunamadı."
        )

    remote_directory = unquote(
        parsed_url.path or ""
    )

    ssh_client = paramiko.SSHClient()
    is_local_test_server = parsed_url.hostname in {
        "127.0.0.1",
        "localhost"
    }

    if is_local_test_server:
        # Rebex yerel test sunucusunun anahtarı ilk bağlantıda bilinmez.
        # Sadece localhost testi için otomatik kabul edilir.
        ssh_client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )
    else:
        # Gerçek uzak sunucularda bilinmeyen anahtarı kabul etmeyiz.
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(
            paramiko.RejectPolicy()
        )

    sftp_client = None

    try:
        ssh_client.connect(
            hostname=parsed_url.hostname,
            port=parsed_url.port or 22,
            username=username,
            password=password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False
        )

        sftp_client = ssh_client.open_sftp()

        if remote_directory:
            sftp_client.chdir(
                remote_directory
            )

        with sftp_client.file(
            file_name,
            "wb"
        ) as remote_file:
            remote_file.write(
                content_bytes
            )

        return {
            "file_name": file_name,
            "server": parsed_url.hostname,
            "directory": remote_directory or "."
        }

    finally:
        if sftp_client is not None:
            sftp_client.close()

        ssh_client.close()


def send_via_json_api(
    content_bytes,
    file_name,
    destination,
    username="",
    password="",
    timeout=15
):
    """Hazırlanan JSON içeriğini HTTP API'ye POST eder."""

    parsed_url = urlparse(
        destination
    )

    if parsed_url.scheme.lower() not in {
        "http",
        "https"
    }:
        raise ValueError(
            "JSON API adresi http:// veya https:// ile başlamalıdır."
        )

    if not parsed_url.hostname:
        raise ValueError(
            "JSON API adresinde sunucu adı bulunamadı."
        )

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Content-Disposition": (
            f'attachment; filename="{file_name}"'
        )
    }

    if username:
        headers[
            "X-API-User"
        ] = username

    if password:
        headers[
            "Authorization"
        ] = f"Bearer {password}"

    request = Request(
        destination,
        data=content_bytes,
        headers=headers,
        method="POST"
    )

    with urlopen(
        request,
        timeout=timeout
    ) as response:
        response.read(1024)

        return {
            "file_name": file_name,
            "server": parsed_url.hostname,
            "status_code": response.status
        }
