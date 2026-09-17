import io
import struct

from modbus_adapters import (
    calculate_modbus_crc,
    create_modbus_rtu_request,
    decode_modbus_rtu_response
)


def create_test_response():
    """Unit ID 1 için 253 değerini taşıyan örnek RTU cevabı oluşturur."""

    response_without_crc = bytes.fromhex(
        "01 03 02 00 FD"
    )

    crc = calculate_modbus_crc(
        response_without_crc
    )

    return response_without_crc + struct.pack(
        "<H",
        crc
    )


def main():
    expected_request = bytes.fromhex(
        "01 03 00 00 00 01 84 0A"
    )

    actual_request = create_modbus_rtu_request(
        unit_id=1,
        function_code=3,
        address=0,
        count=1
    )

    if actual_request != expected_request:
        raise AssertionError(
            "RTU istek paketi beklenen değerle eşleşmiyor."
        )

    print(
        "RTU istek paketi doğru: "
        f"{actual_request.hex(' ')}"
    )

    test_response = create_test_response()
    register_values = decode_modbus_rtu_response(
        io.BytesIO(test_response),
        expected_unit_id=1,
        expected_function_code=3,
        data_type="u16"
    )

    if register_values != [253]:
        raise AssertionError(
            f"RTU cevabı beklenmedik: {register_values}"
        )

    print(
        f"RTU cevap çözümleme başarılı: {register_values}"
    )
    print("RTU temel testi başarılı.")


if __name__ == "__main__":
    main()
