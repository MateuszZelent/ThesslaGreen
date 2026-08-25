from pymodbus.client import ModbusSerialClient

PORT = "COM3"     # <-- zmień na swój port COM

client = ModbusSerialClient(
    port=PORT,
    baudrate=9600,
    bytesize=8,
    parity="N",
    stopbits=1,
    timeout=3,
)

print(f"Łączenie przez {PORT}...")

if not client.connect():
    print("BŁĄD: Nie można otworzyć portu COM.")
    raise SystemExit(1)

print("Port COM otwarty.")

try:
    result = client.read_input_registers(
        address=0x0010,
        count=1,
        device_id=10,
    )

    if result.isError():
        print("BŁĄD MODBUS:")
        print(result)
    else:
        raw = result.registers[0]

        print(f"RAW: {raw} / 0x{raw:04X}")

        if raw == 0x8000:
            print("Rekuperator odpowiada, ale czujnik temperatury nie ma odczytu.")
        else:
            # konwersja uint16 -> int16
            if raw >= 0x8000:
                raw -= 0x10000

            temperature = raw * 0.1
            print(f"Temperatura zewnętrzna: {temperature:.1f} °C")

finally:
    client.close()