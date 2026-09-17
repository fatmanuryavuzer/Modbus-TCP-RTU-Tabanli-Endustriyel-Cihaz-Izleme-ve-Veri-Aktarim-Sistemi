import json
import socket
import struct
from pathlib import Path


CONFIG_FILE = Path(__file__).with_name(
    "05_device_config.json"
)


def load_configuration():
    """
    JSON ayar dosyasını okur
    ve Python sözlüğüne dönüştürür.
    """

    with CONFIG_FILE.open(
        "r",
        encoding="utf-8"
    ) as file:
        configuration = json.load(file)

    return configuration
def receive_exact(connection, size):
    """
    TCP üzerinden tam olarak istenen miktarda byte okur.
    """

    data = b""

    while len(data) < size:
        piece = connection.recv(size - len(data))

        if not piece:
            raise ConnectionError(
                "Server bağlantıyı kapattı."
            )

        data += piece

    return data
def create_modbus_request(
    transaction_id,
    unit_id,
    function_code,
    address,
    count
):
    """
    Modbus TCP istek paketi oluşturur.
    """

    request_pdu = struct.pack(
        ">BHH",
        function_code,
        address,
        count
    )

    request_mbap = struct.pack(
        ">HHHB",
        transaction_id,
        0,
        1 + len(request_pdu),
        unit_id
    )

    return request_mbap + request_pdu

def decode_modbus_response(
    connection,
    expected_transaction_id,
    expected_unit_id
):
    """
    Server'dan gelen Modbus TCP cevabını okur
    ve register değerlerini liste olarak döndürür.
    """

    response_mbap = receive_exact(
        connection,
        7
    )

    (
        response_transaction_id,
        response_protocol_id,
        response_length,
        response_unit_id
    ) = struct.unpack(
        ">HHHB",
        response_mbap
    )

    response_pdu = receive_exact(
        connection,
        response_length - 1
    )

    response_function_code = response_pdu[0]

    if response_function_code & 0x80:
        exception_code = response_pdu[1]

        raise RuntimeError(
            f"Modbus hatası. Hata kodu: {exception_code}"
        )

    if response_transaction_id != expected_transaction_id:
        raise RuntimeError(
            "Transaction ID eşleşmiyor."
        )

    if response_protocol_id != 0:
        raise RuntimeError(
            "Protocol ID hatalı."
        )

    if response_unit_id != expected_unit_id:
        raise RuntimeError(
            "Unit ID eşleşmiyor."
        )

    byte_count = response_pdu[1]

    register_data = response_pdu[
        2:2 + byte_count
    ]

    if byte_count % 2 != 0:
        raise RuntimeError(
            "Register verisi çift sayıda byte olmalı."
        )

    register_values = list(
        struct.unpack(
            ">" + "H" * (byte_count // 2),
            register_data
        )
    )

    return register_values

def read_measurement(
    device,
    measurement,
    transaction_id
):
    """
    Bir cihazdaki bir ölçümü Modbus TCP ile okur.
    """

    host = device["host"]
    port = int(device["port"])
    unit_id = int(device["unit_id"])

    function_code = int(
        measurement["function_code"]
    )
    address = int(
        measurement["address"]
    )
    count = int(
        measurement["count"]
    )
    scale = float(
        measurement["scale"]
    )

    unit = measurement["unit"]
    measurement_name = measurement["name"]

    request = create_modbus_request(
        transaction_id,
        unit_id,
        function_code,
        address,
        count
    )

    print()
    print(f"Cihaz: {device['name']}")
    print(f"Ölçüm: {measurement_name}")
    print(f"Unit ID: {unit_id}")
    print(f"Register adresi: {address}")
    print(f"Register adedi: {count}")

    print("Gönderilen Modbus paketi:")
    print(request.hex(" "))

    with socket.create_connection(
        (host, port),
        timeout=3
    ) as connection:

        print(
            f"{host}:{port} adresine bağlanıldı."
        )

        connection.sendall(request)

        register_values = decode_modbus_response(
            connection,
            transaction_id,
            unit_id
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

def main():
    """
     JSON'daki bütün cihazları ve ölçümleri dolaşır.
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

    transaction_id = 1

    for device in devices:
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
            read_measurement(
                device,
                measurement,
                transaction_id
            )

            transaction_id += 1


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

    except Exception as error:
        print(
            f"HATA: {error}"
        )