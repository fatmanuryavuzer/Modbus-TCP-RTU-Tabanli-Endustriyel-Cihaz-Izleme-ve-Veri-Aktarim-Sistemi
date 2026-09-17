import socket
import struct
import sys

from config_validator import (
    ConfigurationError,
    validate_configuration
)
from database import load_configuration_from_database
from rtu_simulator import start_rtu_server
from simulation_data import (
    DEVICE_NAMES,
    DEVICE_REGISTERS,
    get_register_values,
    refresh_simulation_state_if_changed,
    start_simulation
)


HOST = "127.0.0.1"
PORT = 1502


def load_configuration():
    """Server ayarlarını SQLite veritabanından okur."""

    configuration = load_configuration_from_database()

    validate_configuration(configuration)

    return configuration


def load_simulation_settings(configuration):
    """Server ve RTU simülatörü ayarlarını döndürür."""

    return configuration.get(
        "simulation",
        {}
    )


def load_tcp_unit_ids(configuration):
    """Yalnızca TCP olarak tanımlanan Unit ID'leri döndürür."""

    return {
        int(device["unit_id"])
        for device in configuration.get("devices", [])
        if str(
            device.get("protocol", "tcp")
        ).lower() == "tcp"
        and device.get("enabled", True)
    }


def receive_exact(connection, size):
    """TCP'den tam olarak 'size' kadar byte okuyana kadar bekler."""
    data = b""

    while len(data) < size:
        piece = connection.recv(size - len(data))

        if not piece:
            return None

        data += piece

    return data


def create_response(transaction_id, protocol_id, unit_id, pdu):
    """PDU'nun önüne Modbus TCP MBAP başlığını ekler."""
    length = 1 + len(pdu)
    mbap = struct.pack(">HHHB", transaction_id, protocol_id, length, unit_id)
    return mbap + pdu


def create_register_response(function_code, register_values):
    """Register değerlerini FC03 cevap PDU'suna dönüştürür."""
    register_bytes = b"".join(
        struct.pack(">H", value)
        for value in register_values
    )

    return bytes([function_code, len(register_bytes)]) + register_bytes


def create_error_response(function_code, exception_code):
    """Modbus exception cevabı oluşturur."""
    return bytes([function_code | 0x80, exception_code])


def main(rtu_port=None):
    configuration = load_configuration()
    simulation_settings = load_simulation_settings(
        configuration
    )
    tcp_unit_ids = load_tcp_unit_ids(
        configuration
    )

    if rtu_port:
        simulation_settings["rtu_enabled"] = True
        simulation_settings["serial_port"] = rtu_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(1)

        print(f"Çoklu cihaz Modbus TCP server çalışıyor: {HOST}:{PORT}")
        print("Desteklenen cihazlar:")

        for unit_id, registers in DEVICE_REGISTERS.items():
            if unit_id not in tcp_unit_ids:
                continue

            print(
                f"  Unit ID {unit_id} | {DEVICE_NAMES[unit_id]} | "
                f"Registerlar: {registers}"
            )

        print("\nBağlantı bekleniyor...\n")

        start_simulation()

        print("Simülasyon veri üreticisi çalışıyor.\n")

        if simulation_settings.get(
            "rtu_enabled",
            False
        ):
            rtu_serial_port = simulation_settings.get(
                "serial_port",
                ""
            )

            if not rtu_serial_port:
                print(
                    "RTU etkin fakat serial_port ayarı boş; "
                    "RTU simülatörü başlatılmadı."
                )
            else:
                start_rtu_server(
                    serial_port=rtu_serial_port,
                    baudrate=int(
                        simulation_settings.get(
                            "baudrate",
                            9600
                        )
                    ),
                    parity=simulation_settings.get(
                        "parity",
                        "N"
                    ),
                    stopbits=float(
                        simulation_settings.get(
                            "stopbits",
                            1
                        )
                    ),
                    bytesize=int(
                        simulation_settings.get(
                            "bytesize",
                            8
                        )
                    ),
                    timeout=float(
                        simulation_settings.get(
                            "timeout",
                            1
                        )
                    )
                )

        while True:
            connection, address = server_socket.accept()
            print(f"Client bağlantısı geldi: {address}")

            with connection:
                while True:
                    # Modbus TCP MBAP başlığı 7 byte'tır.
                    mbap = receive_exact(connection, 7)

                    if mbap is None:
                        break

                    transaction_id, protocol_id, length, unit_id = struct.unpack(
                        ">HHHB", mbap
                    )

                    # Length alanında Unit ID'den sonraki PDU uzunluğu bulunur.
                    pdu = receive_exact(connection, length - 1)

                    if pdu is None or len(pdu) < 1:
                        break

                    print("Gelen Modbus paketi:", (mbap + pdu).hex(" "))

                    current_configuration = load_configuration()
                    tcp_unit_ids = load_tcp_unit_ids(
                        current_configuration
                    )
                    if refresh_simulation_state_if_changed():
                        print(
                            "Cihaz ve register tanımları otomatik yenilendi."
                        )

                    function_code = pdu[0]

                    if unit_id not in tcp_unit_ids:
                        print(f"Bilinmeyen Unit ID: {unit_id}")
                        response_pdu = create_error_response(function_code, 0x0B)

                    elif function_code != 3:
                        print(f"Desteklenmeyen Function Code: {function_code}")
                        response_pdu = create_error_response(function_code, 0x01)

                    elif len(pdu) < 5:
                        print("İstek PDU'su eksik.")
                        response_pdu = create_error_response(function_code, 0x03)

                    else:
                        start_address, count = struct.unpack(">HH", pdu[1:5])

                        print(
                            f"Unit ID: {unit_id} | Function Code: {function_code} | "
                            f"Adres: {start_address} | Adet: {count}"
                        )

                        register_values = get_register_values(
                            unit_id,
                            start_address,
                            count
                        )

                        if register_values is None:
                            print("İstenen register adresi bulunamadı.")
                            response_pdu = create_error_response(function_code, 0x02)

                        else:
                            print(
                                f"{DEVICE_NAMES[unit_id]} değerleri: "
                                f"{register_values}"
                            )

                            response_pdu = create_register_response(
                                function_code,
                                register_values,
                            )

                    response = create_response(
                        transaction_id,
                        protocol_id,
                        unit_id,
                        response_pdu,
                    )

                    print("Gönderilen Modbus paketi:", response.hex(" "))
                    connection.sendall(response)

            print("Client bağlantısı kapandı.\n")


if __name__ == "__main__":
    try:
        rtu_port = (
            sys.argv[1]
            if len(sys.argv) > 1
            else None
        )
        main(rtu_port)
    except KeyboardInterrupt:
        print("\nÇoklu cihaz server durduruldu.")
    except ConfigurationError as error:
        print("HATA: SQLite yapılandırması doğrulaması başarısız.")
        print(error)
