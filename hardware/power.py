import smbus2

def get_battery():
    bus = smbus2.SMBus(1)
    soc = bus.read_word_data(0x36, 0x0C)
    soc = ((soc & 0xFF00) >> 8) | ((soc & 0x00FF) << 8)
    percent = int(soc / 256)
    volt_raw = bus.read_word_data(0x36, 0x02)
    volt_raw = ((volt_raw & 0xFF00) >> 8) | ((volt_raw & 0x00FF) << 8)
    voltage = round(volt_raw * 0.000078125, 2)
    return max(0, min(100, percent)), voltage
