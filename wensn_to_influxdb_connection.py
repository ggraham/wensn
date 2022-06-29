import time
import usb.core
from typing import NamedTuple
from influxdb import InfluxDBClient

# Inspired by ebswift, https://www.ebswift.com/reverse-engineering-spl-usb.html

# The Wensn WS1381 answers these bRequests
# 1 seems to be constant - array of 2 bytes returned
# 2 readMode - array of 1 byte returned
# 3 setMode - array of 1 byte returned
# 4 read SPL - array of 2 bytes returned
# 82 array of 4 bytes returned

class SensorData(NamedTuple):
    measurement: str
    location: str
    range: str
    speed: str
    value: str

INFLUXDB_ADDRESS='YOUR INFLUXDB ADDRESS'
INFLUXDB_USER='YOUR INFLUXDB USER'
INFLUXDB_PASSWORD='YOUR INFLUXDB PASSWORD'
INFLUXDB_DATABASE='YOUR INFLUXDB DB NAME'

influxdb_client = InfluxDBClient(INFLUXDB_ADDRESS, 8086, INFLUXDB_USER, INFLUXDB_PASSWORD, None)

ranges = ["30-80", "40-90", "50-100", "60-110", "70-120", "80-130", "30-130"]
speeds = ["fast", "slow"]
weights = ["A", "C"]
maxModes = ["instant", "max"]

def connect():
    dev = usb.core.find(idVendor=0x16c0, idProduct=0x5dc)
    assert dev is not None
    print(dev)
    return dev

def readBRequest(dev, bRequest):
    ret = dev.ctrl_transfer(0xC0, bRequest, 0, 10, 200)
    print(ret),
    for elem in ret:
        print(format(elem, '#010b')),
    print

def readMode(dev):
    ret = dev.ctrl_transfer(0xC0, 2, 0, 10, 200)
    #print(ret)
    #print(format(ret[0], '#010b'))

    rangeN = (ret[0]&7) # bits 1,2,3 in ret[0] return rangeN from 0 to 6
    weightN = (ret[0]&8)>>3 # bit 3 in ret[0] returns weight
    speedN = (ret[0]&16)>>4 # bit 4 in ret[0] returns speed
    maxModeN = (ret[0]&32)>>5 # bit 5 in ret[0] returns maxMode

    return(ranges[rangeN], weights[weightN],
           speeds[speedN], maxModes[maxModeN])

def setMode(dev, range="30-80", speed="slow", weight="C", maxMode="instant"):
    rangeN = ranges[0:4].index(range)
    # For rangeN, setting over USB supports only 2 bits of range,
    #   although 7 values (0 to 6) can be set with buttons on unit.
    speedN = speeds.index(speed)
    weightN = weights.index(weight)
    maxModeN = maxModes.index(maxMode)

    print("setMode: range:%s weight:%s speed:%s maxMode:%s" %
          (range, weight, speed, maxMode))
    #wvalue = rangeN | weightN<<3 | speedN<<4 | maxModeN<<5
    wvalue = (rangeN&3) | (weightN&1)<<3 | (speedN&1)<<4 | (maxModeN&1)<<5
    # Function of bits 6 and 7 is unknown (nothing?)

    dev.ctrl_transfer(0xC0, 3, wvalue, 0, 200)

peak = 0
def readSPL(dev):
    global peak

    ret = dev.ctrl_transfer(0xC0, 4, 0, 10, 200) # wvalue (3rd arg) is ignored
    #print(ret)
    #print(format(ret[1], '#010b'))

    rangeN = (ret[1]&28)>>2 # bits 2,3,4 in ret[1] return rangeN from 0 to 6
    weightN = (ret[1]&32)>>5 # bit 5 in ret[1] return weightN
    speedN = (ret[1]&64)>>6 # bit 6 in ret[1] return speedN
    # bit 7 seems to alternate every 1 second?

    dB = (ret[0] + ((ret[1] & 3) * 256)) * 0.1 + 30
    if dB > peak:
        peak = dB
    return(dB, ranges[rangeN], weights[weightN], speeds[speedN])

def writeToInfluxdb(sensor_data):
    json_body = [
            {
                'measurement': sensor_data.measurement,
                'tags': {
                    'location': sensor_data.location,
                    },
                'fields': {
                    'value': sensor_data.value
                    }
                }
            ]
    influxdb_client.write_points(json_body)

def initInfluxdbDatabase():
    databases = influxdb_client.get_list_database()
    if len(list(filter(lambda x: x['name'] == INFLUXDB_DATABASE, databases))) == 0:
        influxdb_client.create_database(INFLUXDB_DATABASE)
    influxdb_client.switch_database(INFLUXDB_DATABASE)

if __name__ == "__main__":
    # connect to WS1381 over USB
    dev = connect()
    initInfluxdbDatabase()
    # set default modes: "A" weighting, "slow"
    setMode(dev)
    i=0
    while True:
        # roll over to a new log whenever the filename changes - in this case, every hour.
        dB, range, weight, speed = readSPL(dev)
        data=SensorData(measurement = 'sound', location = 'YOUR SENSOR LOCATION', range = range, speed = speed, value = dB)
        if i==0:
            oldData=data
        else:
            if data.value > oldData.value:
                oldData=data
        i+=1
        if i==31:
            writeToInfluxdb(oldData)
            i=0
        time.sleep(1)


