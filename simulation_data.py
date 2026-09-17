import json
import random
import threading
import time

from database import load_configuration_from_database


REGISTER_LOCK = threading.Lock()


def clamp(value, minimum, maximum):
    """Değeri belirlenen minimum ve maksimum arasında tutar."""

    return max(
        minimum,
        min(value, maximum)
    )


def _raw_value_from_engineering_value(value, scale):
    """Gerçek değeri Modbus register'ında tutulacak ham değere çevirir."""

    if scale in (None, 0):
        return int(round(value))

    return int(round(value / scale))


def _initial_engineering_value(measurement):
    """Ölçüm türüne göre gerçekçi başlangıç değeri üretir."""

    measurement_key = str(
        measurement.get("key", "")
    ).lower()

    if "negative" in measurement_key:
        return -10

    if "temperature" in measurement_key:
        return 25

    if "voltage" in measurement_key:
        return 230

    if "energy" in measurement_key:
        return 100

    return 100


def _build_simulation_state(configuration=None):
    """SQLite tanımlarından sanal cihaz register belleğini oluşturur."""

    if configuration is None:
        configuration = load_configuration_from_database()

    device_registers = {}
    device_names = {}
    measurement_profiles = []

    for device in configuration.get("devices", []):
        unit_id = int(device["unit_id"])
        device_registers[unit_id] = {}
        device_names[unit_id] = device["name"]

        for measurement in device.get("measurements", []):
            address = int(measurement["address"])
            count = int(measurement["count"])
            data_type = str(
                measurement["data_type"]
            ).lower()
            scale = float(
                measurement.get("scale", 1)
            )

            raw_value = _raw_value_from_engineering_value(
                _initial_engineering_value(measurement),
                scale
            )

            if data_type == "u32":
                raw_value = clamp(
                    raw_value,
                    0,
                    0xFFFFFFFF
                )
                register_values = [
                    (raw_value >> 16) & 0xFFFF,
                    raw_value & 0xFFFF
                ]
            elif data_type == "s16":
                raw_value = clamp(
                    raw_value,
                    -32768,
                    32767
                )
                register_values = [
                    raw_value & 0xFFFF
                ]
            else:
                raw_value = clamp(
                    raw_value,
                    0,
                    0xFFFF
                )
                register_values = [
                    raw_value
                ]

            if len(register_values) != count:
                raise ValueError(
                    f"{device['key']} / {measurement['key']} için "
                    "register sayısı veri tipiyle uyuşmuyor."
                )

            for offset, register_value in enumerate(
                register_values
            ):
                register_address = address + offset

                if register_address in device_registers[unit_id]:
                    raise ValueError(
                        f"Unit ID {unit_id} içinde register adresi "
                        f"tekrar ediyor: {register_address}"
                    )

                device_registers[unit_id][register_address] = (
                    register_value
                )

            measurement_profiles.append(
                {
                    "unit_id": unit_id,
                    "address": address,
                    "data_type": data_type,
                    "measurement_key": measurement.get(
                        "key",
                        ""
                    )
                }
            )

    return (
        device_registers,
        device_names,
        measurement_profiles
    )


DEVICE_REGISTERS = {}
DEVICE_NAMES = {}
MEASUREMENT_PROFILES = []
SIMULATION_CONFIG_SIGNATURE = None


def _configuration_signature(configuration):
    """Cihaz ve ölçüm tanımlarındaki değişiklikleri karşılaştırır."""

    return json.dumps(
        configuration.get("devices", []),
        ensure_ascii=False,
        sort_keys=True,
        default=str
    )


def refresh_simulation_state_if_changed():
    """SQLite tanımları değiştiyse simülasyon belleğini yeniden yükler."""

    global SIMULATION_CONFIG_SIGNATURE

    configuration = load_configuration_from_database()
    signature = _configuration_signature(configuration)

    with REGISTER_LOCK:
        if signature == SIMULATION_CONFIG_SIGNATURE:
            return False

        (
            new_device_registers,
            new_device_names,
            new_measurement_profiles
        ) = _build_simulation_state(configuration)

        # Sözlük ve listenin kendisi korunuyor. Böylece bu modülü içe aktaran
        # server kodu da yeni cihazları yeniden başlatma olmadan görür.
        DEVICE_REGISTERS.clear()
        DEVICE_REGISTERS.update(new_device_registers)
        DEVICE_NAMES.clear()
        DEVICE_NAMES.update(new_device_names)
        MEASUREMENT_PROFILES.clear()
        MEASUREMENT_PROFILES.extend(new_measurement_profiles)
        SIMULATION_CONFIG_SIGNATURE = signature

    return True


refresh_simulation_state_if_changed()


def update_unsigned_register(
    registers,
    address,
    minimum,
    maximum,
    step
):
    """İşaretsiz register değerini küçük rastgele adımlarla değiştirir."""

    current_value = registers[address]
    change = random.randint(-step, step)
    new_value = current_value + change

    registers[address] = clamp(
        new_value,
        minimum,
        maximum
    )


def update_signed_register(
    registers,
    address,
    minimum,
    maximum,
    step
):
    """S16 register değerini signed biçimde değiştirir."""

    raw_value = registers[address]

    if raw_value >= 0x8000:
        current_value = raw_value - 0x10000
    else:
        current_value = raw_value

    change = random.randint(-step, step)
    new_value = clamp(
        current_value + change,
        minimum,
        maximum
    )

    registers[address] = new_value & 0xFFFF


def update_energy_register(registers, address):
    """İki registerlık U32 enerji değerini küçük miktarda artırır."""

    energy_value = (
        registers[address] << 16
    ) | registers[address + 1]

    energy_value += random.randint(1, 20)
    energy_value = clamp(
        energy_value,
        0,
        0xFFFFFFFF
    )

    registers[address] = (energy_value >> 16) & 0xFFFF
    registers[address + 1] = energy_value & 0xFFFF


def _get_update_limits(measurement_profile):
    """Ölçüm türüne göre gerçekçi simülasyon aralığı belirler."""

    measurement_key = str(
        measurement_profile.get("measurement_key", "")
    ).lower()
    data_type = measurement_profile["data_type"]

    if data_type == "s16":
        if "negative" in measurement_key:
            return -200, 0, 2

        return -30000, 30000, 2

    if "temperature" in measurement_key:
        return 150, 400, 2

    if "voltage" in measurement_key:
        return 2200, 2400, 3

    return 0, 0xFFFF, 1


def update_simulated_devices():
    """Sanal cihazların register değerlerini sürekli günceller."""

    while True:
        with REGISTER_LOCK:
            for measurement_profile in MEASUREMENT_PROFILES:
                registers = DEVICE_REGISTERS[
                    measurement_profile["unit_id"]
                ]
                address = measurement_profile["address"]
                data_type = measurement_profile["data_type"]

                if data_type == "u32":
                    update_energy_register(
                        registers,
                        address
                    )
                    continue

                minimum, maximum, step = _get_update_limits(
                    measurement_profile
                )

                if data_type == "s16":
                    update_signed_register(
                        registers,
                        address,
                        minimum,
                        maximum,
                        step
                    )
                else:
                    update_unsigned_register(
                        registers,
                        address,
                        minimum,
                        maximum,
                        step
                    )

        time.sleep(1)


def get_register_values(
    unit_id,
    start_address,
    count
):
    """Ortak register belleğinden istenen değerleri güvenli şekilde alır."""

    with REGISTER_LOCK:
        device_registers = DEVICE_REGISTERS.get(unit_id)

        if device_registers is None or count < 1:
            return None

        requested_addresses = range(
            start_address,
            start_address + count
        )

        if not all(
            address in device_registers
            for address in requested_addresses
        ):
            return None

        return [
            device_registers[address]
            for address in requested_addresses
        ]


def start_simulation():
    """Ortak simülasyon veri üreticisini arka planda başlatır."""

    generator_thread = threading.Thread(
        target=update_simulated_devices,
        daemon=True
    )
    generator_thread.start()

    return generator_thread
