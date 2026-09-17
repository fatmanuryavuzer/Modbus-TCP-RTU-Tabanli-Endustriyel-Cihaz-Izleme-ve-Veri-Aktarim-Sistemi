"""05_device_config.json için ayar doğrulama yardımcıları."""


ALLOWED_PROTOCOLS = {
    "tcp",
    "rtu"
}

ALLOWED_TRANSPORTS = {
    "memory",
    "serial"
}

ALLOWED_DATA_TYPES = {
    "u16",
    "s16",
    "u32"
}


class ConfigurationError(ValueError):
    """Ayar dosyası beklenen kurallara uymadığında oluşur."""


def is_integer(value):
    """Bool değerlerini integer kabul etmeden tam sayı kontrolü yapar."""

    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    """Bool değerlerini sayı kabul etmeden sayısal değer kontrolü yapar."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_non_empty_text(value):
    """Değerin boş olmayan bir metin olup olmadığını kontrol eder."""

    return isinstance(value, str) and bool(value.strip())


def add_required_text_error(
    record,
    field_name,
    location,
    errors
):
    """Zorunlu metin alanı eksikse hata listesine ekler."""

    if not is_non_empty_text(record.get(field_name)):
        errors.append(
            f"{location} için '{field_name}' boş veya eksik."
        )


def validate_measurement(
    measurement,
    device_location,
    measurement_keys,
    errors
):
    """Tek bir ölçüm tanımını kontrol eder."""

    if not isinstance(measurement, dict):
        errors.append(
            f"{device_location} içindeki ölçüm sözlük biçiminde olmalı."
        )
        return

    measurement_location = (
        f"{device_location} ölçümü"
    )

    add_required_text_error(
        measurement,
        "key",
        measurement_location,
        errors
    )
    add_required_text_error(
        measurement,
        "name",
        measurement_location,
        errors
    )
    add_required_text_error(
        measurement,
        "unit",
        measurement_location,
        errors
    )

    measurement_key = measurement.get("key")

    if is_non_empty_text(measurement_key):
        if measurement_key in measurement_keys:
            errors.append(
                f"{measurement_location} key değeri tekrar ediyor: "
                f"'{measurement_key}'."
            )
        else:
            measurement_keys.add(measurement_key)

    function_code = measurement.get("function_code")

    if not is_integer(function_code):
        errors.append(
            f"{measurement_location} için function_code tam sayı olmalı."
        )
    elif function_code != 3:
        errors.append(
            f"{measurement_location} için function_code şu an yalnızca 3 "
            f"olabilir; verilen değer: {function_code}."
        )

    address = measurement.get("address")

    if not is_integer(address):
        errors.append(
            f"{measurement_location} için address tam sayı olmalı."
        )
    elif not 0 <= address <= 65535:
        errors.append(
            f"{measurement_location} address değeri 0 ile 65535 arasında "
            "olmalı."
        )

    count = measurement.get("count")

    if not is_integer(count):
        errors.append(
            f"{measurement_location} için count tam sayı olmalı."
        )
    elif not 1 <= count <= 125:
        errors.append(
            f"{measurement_location} count değeri 1 ile 125 arasında "
            "olmalı."
        )

    data_type = measurement.get("data_type")

    if data_type not in ALLOWED_DATA_TYPES:
        allowed_types = ", ".join(
            sorted(ALLOWED_DATA_TYPES)
        )
        errors.append(
            f"{measurement_location} data_type desteklenmiyor: "
            f"'{data_type}'. Kullanılabilecek tipler: {allowed_types}."
        )
    elif is_integer(count):
        required_count = {
            "u16": 1,
            "s16": 1,
            "u32": 2
        }[data_type]

        if count != required_count:
            errors.append(
                f"{measurement_location} '{data_type}' için count "
                f"{required_count} olmalı."
            )

    scale = measurement.get("scale")

    if not is_number(scale):
        errors.append(
            f"{measurement_location} için scale sayısal olmalı."
        )
    elif scale <= 0:
        errors.append(
            f"{measurement_location} için scale sıfırdan büyük olmalı."
        )

    if (
        is_integer(address)
        and is_integer(count)
        and address + count > 65536
    ):
        errors.append(
            f"{measurement_location} register aralığı 65535 adresini "
            "aşıyor."
        )


def validate_device(
    device,
    index,
    device_keys,
    unit_ids,
    errors
):
    """Tek bir cihaz tanımını ve ölçümlerini kontrol eder."""

    device_location = f"devices[{index}]"

    if not isinstance(device, dict):
        errors.append(
            f"{device_location} sözlük biçiminde olmalı."
        )
        return

    add_required_text_error(
        device,
        "key",
        device_location,
        errors
    )
    add_required_text_error(
        device,
        "name",
        device_location,
        errors
    )

    device_key = device.get("key")

    if is_non_empty_text(device_key):
        if device_key in device_keys:
            errors.append(
                f"Cihaz key değeri tekrar ediyor: '{device_key}'."
            )
        else:
            device_keys.add(device_key)

    protocol = device.get("protocol")

    enabled = device.get("enabled", True)

    if not isinstance(enabled, bool):
        errors.append(
            f"{device_location} enabled doğru/yanlış biçiminde olmalı."
        )

    if not isinstance(protocol, str):
        errors.append(
            f"{device_location} için protocol metin olmalı."
        )
        protocol = ""
    else:
        protocol = protocol.lower()

        if protocol not in ALLOWED_PROTOCOLS:
            errors.append(
                f"{device_location} protocol desteklenmiyor: '{protocol}'. "
                "Kullanılabilecek protokoller: tcp, rtu."
            )

    unit_id = device.get("unit_id")

    if not is_integer(unit_id):
        errors.append(
            f"{device_location} için unit_id tam sayı olmalı."
        )
    elif not 1 <= unit_id <= 247:
        errors.append(
            f"{device_location} unit_id değeri 1 ile 247 arasında olmalı."
        )
    elif unit_id in unit_ids:
        errors.append(
            f"Unit ID tekrar ediyor: {unit_id}."
        )
    else:
        unit_ids.add(unit_id)

    retry_count = device.get("retry_count", 2)

    if not is_integer(retry_count) or retry_count < 0:
        errors.append(
            f"{device_location} retry_count sıfır veya daha büyük bir "
            "tam sayı olmalı."
        )

    retry_delay = device.get("retry_delay", 0.5)

    if not is_number(retry_delay) or retry_delay < 0:
        errors.append(
            f"{device_location} retry_delay sıfır veya daha büyük bir "
            "sayı olmalı."
        )

    timeout = device.get("timeout", 3)

    if not is_number(timeout) or timeout <= 0:
        errors.append(
            f"{device_location} timeout sıfırdan büyük bir sayı olmalı."
        )

    if "baudrate" in device:
        baudrate = device.get("baudrate")

        if not is_integer(baudrate) or baudrate <= 0:
            errors.append(
                f"{device_location} baudrate sıfırdan büyük bir tam sayı "
                "olmalı."
            )

    if "parity" in device:
        parity = device.get("parity")

        if parity not in {"N", "E", "O"}:
            errors.append(
                f"{device_location} parity N, E veya O olmalı."
            )

    if "stopbits" in device:
        stopbits = device.get("stopbits")

        if not is_number(stopbits) or stopbits not in {1, 1.5, 2}:
            errors.append(
                f"{device_location} stopbits 1, 1.5 veya 2 olmalı."
            )

    if "bytesize" in device:
        bytesize = device.get("bytesize")

        if not is_integer(bytesize) or not 5 <= bytesize <= 8:
            errors.append(
                f"{device_location} bytesize 5 ile 8 arasında olmalı."
            )

    if protocol == "tcp":
        if not is_non_empty_text(device.get("host")):
            errors.append(
                f"{device_location} TCP cihazı için host boş veya eksik."
            )

        port = device.get("port")

        if not is_integer(port):
            errors.append(
                f"{device_location} TCP cihazı için port tam sayı olmalı."
            )
        elif not 1 <= port <= 65535:
            errors.append(
                f"{device_location} TCP port değeri 1 ile 65535 arasında "
                "olmalı."
            )

    if protocol == "rtu":
        transport = device.get("transport", "serial")

        if transport not in ALLOWED_TRANSPORTS:
            errors.append(
                f"{device_location} RTU transport desteklenmiyor: "
                f"'{transport}'. Kullanılabilecek değerler: memory, serial."
            )
        elif transport == "serial":
            serial_port = device.get(
                "serial_port",
                device.get("port")
            )

            if not is_non_empty_text(serial_port):
                errors.append(
                    f"{device_location} gerçek RTU cihazı için serial_port "
                    "veya port bilgisi gerekli."
                )

    measurements = device.get("measurements")

    if not isinstance(measurements, list):
        errors.append(
            f"{device_location} measurements liste biçiminde olmalı."
        )
        return

    # Cihaz, ölçüm register'ları daha sonra tanımlanmak üzere
    # önce temel bağlantı bilgileriyle kaydedilebilir.
    if not measurements:
        return

    measurement_keys = set()
    register_ranges = []

    for measurement in measurements:
        validate_measurement(
            measurement,
            device_location,
            measurement_keys,
            errors
        )

        if not isinstance(measurement, dict):
            continue

        address = measurement.get("address")
        count = measurement.get("count")

        if (
            is_integer(address)
            and is_integer(count)
            and 0 <= address <= 65535
            and 1 <= count <= 125
        ):
            range_end = address + count

            for previous_start, previous_end, previous_key in register_ranges:
                if (
                    address < previous_end
                    and previous_start < range_end
                ):
                    errors.append(
                        f"{device_location} içinde register aralığı "
                        f"'{measurement.get('key')}' ile "
                        f"'{previous_key}' ölçümleri arasında çakışıyor."
                    )

            register_ranges.append(
                (
                    address,
                    range_end,
                    measurement.get("key", "")
                )
            )


def validate_new_device(
    device,
    existing_devices
):
    """Yeni cihazı mevcut cihazlarla birlikte doğrular."""

    errors = []
    existing_devices = existing_devices or []

    device_keys = {
        existing_device.get("key")
        for existing_device in existing_devices
        if isinstance(existing_device, dict)
    }
    unit_ids = {
        existing_device.get("unit_id")
        for existing_device in existing_devices
        if isinstance(existing_device, dict)
    }

    validate_device(
        device,
        len(existing_devices),
        device_keys,
        unit_ids,
        errors
    )

    if errors:
        error_lines = "\n".join(
            f"- {error}" for error in errors
        )
        raise ConfigurationError(
            "Yeni cihaz doğrulama hataları:\n"
            f"{error_lines}"
        )

    return True


def validate_updated_device(
    device,
    existing_devices,
    original_key
):
    """Güncellenen cihazı, kendi eski kaydını hariç tutarak doğrular."""

    errors = []
    existing_devices = existing_devices or []

    other_devices = [
        existing_device
        for existing_device in existing_devices
        if (
            isinstance(existing_device, dict)
            and existing_device.get("key") != original_key
        )
    ]

    device_keys = {
        existing_device.get("key")
        for existing_device in other_devices
    }
    unit_ids = {
        existing_device.get("unit_id")
        for existing_device in other_devices
    }

    device_index = next(
        (
            index
            for index, existing_device in enumerate(existing_devices)
            if (
                isinstance(existing_device, dict)
                and existing_device.get("key") == original_key
            )
        ),
        len(existing_devices)
    )

    validate_device(
        device,
        device_index,
        device_keys,
        unit_ids,
        errors
    )

    if errors:
        error_lines = "\n".join(
            f"- {error}" for error in errors
        )
        raise ConfigurationError(
            "Cihaz güncelleme doğrulama hataları:\n"
            f"{error_lines}"
        )

    return True


def validate_simulation_settings(
    settings,
    errors
):
    """JSON içindeki genel simülasyon ayarlarını kontrol eder."""

    if not isinstance(settings, dict):
        errors.append(
            "'simulation' alanı sözlük biçiminde olmalı."
        )
        return

    rtu_enabled = settings.get(
        "rtu_enabled",
        False
    )

    if not isinstance(rtu_enabled, bool):
        errors.append(
            "simulation.rtu_enabled doğru/yanlış biçiminde olmalı."
        )

    serial_port = settings.get(
        "serial_port",
        ""
    )

    if not isinstance(serial_port, str):
        errors.append(
            "simulation.serial_port metin biçiminde olmalı."
        )

    baudrate = settings.get(
        "baudrate",
        9600
    )

    if not is_integer(baudrate) or baudrate <= 0:
        errors.append(
            "simulation.baudrate sıfırdan büyük bir tam sayı olmalı."
        )

    parity = settings.get(
        "parity",
        "N"
    )

    if parity not in {"N", "E", "O"}:
        errors.append(
            "simulation.parity N, E veya O olmalı."
        )

    stopbits = settings.get(
        "stopbits",
        1
    )

    if not is_number(stopbits) or stopbits not in {1, 1.5, 2}:
        errors.append(
            "simulation.stopbits 1, 1.5 veya 2 olmalı."
        )

    bytesize = settings.get(
        "bytesize",
        8
    )

    if not is_integer(bytesize) or not 5 <= bytesize <= 8:
        errors.append(
            "simulation.bytesize 5 ile 8 arasında olmalı."
        )

    timeout = settings.get(
        "timeout",
        1
    )

    if not is_number(timeout) or timeout <= 0:
        errors.append(
            "simulation.timeout sıfırdan büyük bir sayı olmalı."
        )


def validate_configuration(configuration):
    """Tüm ayar dosyasını kontrol eder; hata varsa ConfigurationError üretir."""

    errors = []

    if not isinstance(configuration, dict):
        raise ConfigurationError(
            "Ayar dosyasının kökü JSON nesnesi biçiminde olmalı."
        )

    validate_simulation_settings(
        configuration.get(
            "simulation",
            {}
        ),
        errors
    )

    devices = configuration.get("devices")

    if not isinstance(devices, list) or not devices:
        errors.append(
            "'devices' alanı boş olmayan bir liste olmalı."
        )
    else:
        device_keys = set()
        unit_ids = set()

        for index, device in enumerate(devices):
            validate_device(
                device,
                index,
                device_keys,
                unit_ids,
                errors
            )

    if errors:
        error_lines = "\n".join(
            f"- {error}" for error in errors
        )
        raise ConfigurationError(
            "Ayar dosyası doğrulama hataları:\n"
            f"{error_lines}"
        )

    return True
