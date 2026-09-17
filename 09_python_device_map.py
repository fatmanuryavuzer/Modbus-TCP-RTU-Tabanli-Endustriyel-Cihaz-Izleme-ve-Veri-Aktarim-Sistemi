# Her cihazın register değerlerini tutan sözlük.
device_registers = {
    1: {
        0: 253,
        1: 2300
    },
    2: {
        0: 277,
        1: 2310
    },
    3: {
        0: 245,
        1: 2290
    }
}


# Unit ID'si 2 olan cihazın bütün register'larını yazdırır.
print("Unit ID 2 register değerleri:")
print(device_registers[2])


# Unit ID'si 2 olan cihazın register 1 değerini yazdırır.
print()
print("Unit ID 2, Register 1 değeri:")
print(device_registers[2][1])


# Bütün cihazları sırayla gezer.
print()
print("Bütün cihazlar:")

for unit_id, registers in device_registers.items():
    print(f"Unit ID: {unit_id}")
    print(f"Register değerleri: {registers}")
    print()