import socket
import struct
import time


def get_retry_settings(device):
    """Cihaz için tekrar deneme ayarlarını okur."""

    retry_count = int(
        device.get("retry_count", 2)
    )
    retry_delay = float(
        device.get("retry_delay", 0.5)
    )

    if retry_count < 0:
        raise ValueError(
            "retry_count negatif olamaz."
        )

    if retry_delay < 0:
        raise ValueError(
            "retry_delay negatif olamaz."
        )

    return retry_count + 1, retry_delay


def calculate_modbus_crc(data):
    """Modbus RTU çerçevesi için CRC-16 değerini hesaplar."""

    crc = 0xFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc


def create_modbus_rtu_request(
    unit_id,
    function_code,
    address,
    count
):
    """Modbus RTU istek paketini CRC ile birlikte oluşturur."""

    request_without_crc = struct.pack(
        ">BBHH",
        unit_id,
        function_code,
        address,
        count
    )

    crc = calculate_modbus_crc(
        request_without_crc
    )

    return request_without_crc + struct.pack(
        "<H",
        crc
    )


def receive_serial_exact(connection, size):
    """Seri bağlantıdan tam olarak istenen byte sayısını okur."""

    data = connection.read(size)

    if len(data) != size:
        raise TimeoutError(
            f"RTU cevabı eksik geldi. Beklenen byte: {size}, "
            f"gelen byte: {len(data)}"
        )

    return data


def receive_exact(connection, size):
    """TCP bağlantısından tam olarak istenen byte sayısını okur."""

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
    """Modbus TCP istek paketini oluşturur."""

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
    expected_unit_id,
    data_type
):
    """Modbus TCP cevabını kontrol eder ve register değerlerini döndürür."""

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

    if data_type == "u32":
        if byte_count != 4:
            raise RuntimeError(
                "u32 verisi 4 byte olmalı."
            )

        return list(
            struct.unpack(
                ">I",
                register_data
            )
        )

    if data_type == "u16":
        register_format = "H"

    elif data_type == "s16":
        register_format = "h"

    else:
        raise ValueError(
            f"Desteklenmeyen veri tipi: {data_type}"
        )

    return list(
        struct.unpack(
            ">" + register_format * (byte_count // 2),
            register_data
        )
    )


class ModbusTcpAdapter:
    """Modbus TCP üzerinden register okuyan adaptör."""

    def read_registers(
        self,
        device,
        measurement,
        transaction_id,
        data_type
    ):
        """Bir ölçümün ham register değerlerini okur."""

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

        request = create_modbus_request(
            transaction_id,
            unit_id,
            function_code,
            address,
            count
        )

        print("Gönderilen Modbus paketi:")
        print(request.hex(" "))

        max_attempts, retry_delay = get_retry_settings(
            device
        )

        for attempt in range(1, max_attempts + 1):
            try:
                with socket.create_connection(
                    (host, port),
                    timeout=3
                ) as connection:
                    print(
                        f"{host}:{port} adresine bağlanıldı."
                    )

                    connection.sendall(request)

                    return decode_modbus_response(
                        connection,
                        transaction_id,
                        unit_id,
                        data_type
                    )

            except (TimeoutError, ConnectionError, OSError) as error:
                if attempt == max_attempts:
                    raise

                print(
                    f"TCP okuma denemesi {attempt}/{max_attempts} "
                    f"başarısız: {error}"
                )
                print(
                    f"{retry_delay} saniye sonra tekrar denenecek."
                )
                time.sleep(retry_delay)


def decode_modbus_rtu_response(
    connection,
    expected_unit_id,
    expected_function_code,
    data_type
):
    """Modbus RTU cevabını kontrol eder ve register değerlerini döndürür."""

    response_header = receive_serial_exact(
        connection,
        3
    )

    (
        response_unit_id,
        response_function_code,
        byte_count_or_exception
    ) = struct.unpack(
        ">BBB",
        response_header
    )

    if response_unit_id != expected_unit_id:
        raise RuntimeError(
            "RTU Unit ID eşleşmiyor."
        )

    if response_function_code & 0x80:
        response_body = receive_serial_exact(
            connection,
            2
        )

        response_without_crc = response_header
        received_crc = struct.unpack(
            "<H",
            response_body
        )[0]

        calculated_crc = calculate_modbus_crc(
            response_without_crc
        )

        if received_crc != calculated_crc:
            raise RuntimeError(
                "RTU cevabında CRC hatası."
            )

        raise RuntimeError(
            "Modbus RTU hatası. "
            f"Hata kodu: {byte_count_or_exception}"
        )

    if response_function_code != expected_function_code:
        raise RuntimeError(
            "RTU Function Code eşleşmiyor."
        )

    byte_count = byte_count_or_exception

    response_body = receive_serial_exact(
        connection,
        byte_count + 2
    )

    register_data = response_body[:byte_count]
    received_crc = struct.unpack(
        "<H",
        response_body[byte_count:]
    )[0]

    calculated_crc = calculate_modbus_crc(
        response_header + register_data
    )

    if received_crc != calculated_crc:
        raise RuntimeError(
            "RTU cevabında CRC hatası."
        )

    if byte_count % 2 != 0:
        raise RuntimeError(
            "Register verisi çift sayıda byte olmalı."
        )

    if data_type == "u32":
        if byte_count != 4:
            raise RuntimeError(
                "u32 verisi 4 byte olmalı."
            )

        return list(
            struct.unpack(
                ">I",
                register_data
            )
        )

    if data_type == "u16":
        register_format = "H"

    elif data_type == "s16":
        register_format = "h"

    else:
        raise ValueError(
            f"Desteklenmeyen veri tipi: {data_type}"
        )

    return list(
        struct.unpack(
            ">" + register_format * (byte_count // 2),
            register_data
        )
    )


class InMemoryRtuConnection:
    """COM port yerine RTU simülasyonuyla konuşan sahte bağlantı."""

    def __init__(self):
        self.response = b""

    def write(self, request):
        """RTU isteğini simülatöre gönderip cevabı belleğe alır."""

        from rtu_simulator import handle_rtu_request

        self.response = handle_rtu_request(
            request
        )

    def read(self, size):
        """Beklenen byte sayısını cevap belleğinden döndürür."""

        data = self.response[:size]
        self.response = self.response[size:]

        return data


class ModbusRtuAdapter:
    """Modbus RTU üzerinden register okuyan adaptör."""

    def read_registers(
        self,
        device,
        measurement,
        _transaction_id,
        data_type
    ):
        """Bir ölçümün ham register değerlerini RTU ile okur."""

        unit_id = int(
            device["unit_id"]
        )
        function_code = int(
            measurement["function_code"]
        )
        address = int(
            measurement["address"]
        )
        count = int(
            measurement["count"]
        )

        request = create_modbus_rtu_request(
            unit_id,
            function_code,
            address,
            count
        )

        print("Gönderilen Modbus RTU paketi:")
        print(request.hex(" "))

        max_attempts, retry_delay = get_retry_settings(
            device
        )

        if device.get("transport") == "memory":
            for attempt in range(1, max_attempts + 1):
                try:
                    print(
                        "Kod içi RTU simülasyon bağlantısı kullanılıyor."
                    )

                    connection = InMemoryRtuConnection()
                    connection.write(request)

                    return decode_modbus_rtu_response(
                        connection,
                        unit_id,
                        function_code,
                        data_type
                    )

                except (TimeoutError, ConnectionError, OSError) as error:
                    if attempt == max_attempts:
                        raise

                    print(
                        f"RTU okuma denemesi {attempt}/{max_attempts} "
                        f"başarısız: {error}"
                    )
                    print(
                        f"{retry_delay} saniye sonra tekrar denenecek."
                    )
                    time.sleep(retry_delay)

        try:
            import serial
        except ImportError as error:
            raise RuntimeError(
                "Modbus RTU için pyserial kurulmalı: "
                "python -m pip install pyserial"
            ) from error

        serial_port = device.get(
            "serial_port",
            device.get("port")
        )

        if not serial_port:
            raise ValueError(
                "RTU cihazında serial_port alanı bulunmalı."
            )

        baudrate = int(
            device.get("baudrate", 9600)
        )
        parity = device.get(
            "parity",
            "N"
        ).upper()
        stopbits = float(
            device.get("stopbits", 1)
        )
        bytesize = int(
            device.get("bytesize", 8)
        )
        timeout = float(
            device.get("timeout", 3)
        )

        for attempt in range(1, max_attempts + 1):
            try:
                with serial.Serial(
                    port=serial_port,
                    baudrate=baudrate,
                    parity=parity,
                    stopbits=stopbits,
                    bytesize=bytesize,
                    timeout=timeout
                ) as connection:
                    print(
                        f"{serial_port} seri portuna bağlanıldı."
                    )

                    connection.write(request)

                    return decode_modbus_rtu_response(
                        connection,
                        unit_id,
                        function_code,
                        data_type
                    )

            except (TimeoutError, ConnectionError, OSError) as error:
                if attempt == max_attempts:
                    raise

                print(
                    f"RTU okuma denemesi {attempt}/{max_attempts} "
                    f"başarısız: {error}"
                )
                print(
                    f"{retry_delay} saniye sonra tekrar denenecek."
                )
                time.sleep(retry_delay)


def create_adapter(device):
    """Cihazın protocol alanına göre uygun adaptörü oluşturur."""

    protocol = device.get(
        "protocol",
        "tcp"
    ).lower()

    if protocol == "tcp":
        return ModbusTcpAdapter()

    if protocol == "rtu":
        return ModbusRtuAdapter()

    raise ValueError(
        f"Desteklenmeyen protokol: {protocol}"
    )
