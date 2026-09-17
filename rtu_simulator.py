import struct
import threading

from modbus_adapters import calculate_modbus_crc
from simulation_data import get_register_values


def create_rtu_register_response(
    unit_id,
    function_code,
    register_values
):
    """Register değerlerini Modbus RTU cevap paketine dönüştürür."""

    register_bytes = b"".join(
        struct.pack(">H", value)
        for value in register_values
    )

    response_without_crc = bytes(
        [unit_id, function_code, len(register_bytes)]
    ) + register_bytes

    crc = calculate_modbus_crc(
        response_without_crc
    )

    return response_without_crc + struct.pack(
        "<H",
        crc
    )


def create_rtu_error_response(
    unit_id,
    function_code,
    exception_code
):
    """Modbus RTU exception cevap paketi oluşturur."""

    response_without_crc = bytes(
        [unit_id, function_code | 0x80, exception_code]
    )

    crc = calculate_modbus_crc(
        response_without_crc
    )

    return response_without_crc + struct.pack(
        "<H",
        crc
    )


def handle_rtu_request(request):
    """RTU isteğini kontrol eder ve ortak register belleğinden cevap üretir."""

    if len(request) != 8:
        raise RuntimeError(
            "RTU isteği 8 byte olmalı."
        )

    request_without_crc = request[:6]
    received_crc = struct.unpack(
        "<H",
        request[6:]
    )[0]
    calculated_crc = calculate_modbus_crc(
        request_without_crc
    )

    if received_crc != calculated_crc:
        raise RuntimeError(
            "RTU isteğinde CRC hatası."
        )

    (
        unit_id,
        function_code,
        start_address,
        count
    ) = struct.unpack(
        ">BBHH",
        request_without_crc
    )

    if function_code != 3:
        return create_rtu_error_response(
            unit_id,
            function_code,
            0x01
        )

    register_values = get_register_values(
        unit_id,
        start_address,
        count
    )

    if register_values is None:
        return create_rtu_error_response(
            unit_id,
            function_code,
            0x02
        )

    return create_rtu_register_response(
        unit_id,
        function_code,
        register_values
    )


def run_rtu_server(
    serial_port,
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1
):
    """Ortak simülasyon belleğini kullanan RTU server’ı çalıştırır."""

    try:
        import serial
    except ImportError as error:
        raise RuntimeError(
            "RTU simülatörü için pyserial kurulmalı."
        ) from error

    with serial.Serial(
        port=serial_port,
        baudrate=baudrate,
        parity=parity,
        stopbits=stopbits,
        bytesize=bytesize,
        timeout=timeout
    ) as connection:
        print(
            f"RTU simülatörü {serial_port} portunda çalışıyor."
        )

        while True:
            request = connection.read(8)

            if not request:
                continue

            print(
                "Gelen RTU paketi:",
                request.hex(" ")
            )

            try:
                response = handle_rtu_request(request)
            except Exception as error:
                print(
                    f"RTU isteği işlenemedi: {error}"
                )
                continue

            print(
                "Gönderilen RTU paketi:",
                response.hex(" ")
            )
            connection.write(response)


def start_rtu_server(
    serial_port,
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1
):
    """RTU server’ı TCP server ile aynı süreçte arka planda başlatır."""

    rtu_thread = threading.Thread(
        target=run_rtu_server,
        args=(
            serial_port,
            baudrate,
            parity,
            stopbits,
            bytesize,
            timeout
        ),
        daemon=True
    )
    rtu_thread.start()

    return rtu_thread
