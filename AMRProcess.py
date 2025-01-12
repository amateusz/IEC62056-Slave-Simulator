#AMR (Automatic Meter Reading Application .py file)

__author__  = "Serbay Ozkan"
__version__ = "1.0.0"
__email__   = "serbay.ozkan@hotmail.com"
__status__  = "Development"

#Import Python Library Modules
import sys
import serial
import io
import threading
import time
import os
import enum

#Constant Definitions
SERIAL_NO_LENGTH = 8
DEBUG_AMR_ENABLE = True
READ_OUT_COMMANDS = ["0"+str(_)+"0" for _ in range(6)]

@enum.unique
class IEC_MAGIC_BYTES(enum.IntEnum):
    STX = 0x02 # start of frame
    ETX = 0x03 # end of frame
    ACK = 0x06 # acknoledge
    NCK = 32 # no acknoledge, repeat
    BCC_LGZ = 0x08 # BCC for LGZ example payload

class AMR_STATE:
    ERROR_PROCESS = -1
    START_PROCESS = 0
    READOUT_PROCESS = 1
    REPEAT = 2

#Class Object Definitions
class AMRParams:
    serialNo = ["", "", "", ""]
    brand = ["", "", "", ""]
    enable = [0, 0, 0, 0]
    requestedSerialNo = ""
    baudrateInStart = 300
    baudrateInRuntime = 9600
    deviceNumber = -1
    comPortName = ""
    parity = ""
    stopBit = 1
    dataBit = 8
    
    def baud_to_iec(baud):
        if baud == 300:
            return 0
        elif baud == 600:
            return 1
        elif baud == 1200:
            return 2
        elif baud == 2400:
            return 3
        elif baud == 4800:
            return 4
        elif baud == 9600:
            return 5
        else:
            return None
        
    def iec_to_baud(iec):
        if iec == 0:
            return 300
        elif iec == 1:
            return 600
        elif iec == 2:
            return 1200
        elif iec == 3:
            return 2400
        elif iec == 4:
            return 4800
        elif iec == 5:
            return 9600
        else:
            return None

#Checks the validty of serial list defined in AMRParams.json by user
def checkUserSerialList():
    success = True

    for i in range(0, len(AMRParams.serialNo)):
        if len(AMRParams.serialNo[i]) != SERIAL_NO_LENGTH:
            print("ERROR_AMR: Please Check User Defined Serial No List!")
            print("HINT_AMR: Serial No length should exist from 8 Digits!")
            success = False

    for i in range(0, len(AMRParams.serialNo)):
        try:
            int (AMRParams.serialNo[i])
        except ValueError:
            print("ERROR_AMR: Please Check User Defined Serial No List!")
            print("HINT_AMR: There should not be any string character in serial no!")
            success = False

    return success

#Gets substring between two special character or string
def getSubString(s, first, last):
    try:
        start = s.index( first ) + len( first )
        end = s.index( last, start )
        return s[start:end]
    except ValueError:
        return ""

#Gets the requested serial number from Master Device
def getSerialNo(inputStr):
    
    if str("MSY") in inputStr:
        requestedSerialNo = getSubString(inputStr, "MSY", "!")
    elif str("/?") in inputStr and str("!") in inputStr:
        requestedSerialNo = getSubString(inputStr, "/?", "!")
        if len(requestedSerialNo) == 0:
            print("WARNING_ARM: device address not specified")
    else:
        requestedSerialNo = "NOT_SUPPORTED"

    return requestedSerialNo

#Checks the requested serial number from AMRParams.json
#If serial number could not exist, user would be informed by console
def checkSeriaNoFromSerialList(requestedSerialNo):
    checkSerialNo = False
    for i in range(0, len(AMRParams.serialNo)):
        if requestedSerialNo == AMRParams.serialNo[i]:
            if DEBUG_AMR_ENABLE:
                print ("DEBUG_AMR: Requested serial number is exist in Serial Device List")
            checkSerialNo = True

    if checkSerialNo == False:
        print ("ERROR_AMR: Requested serial number does not exist in Serial Device List!")
        print ("ERROR_AMR: Requested Serial Number: " + requestedSerialNo)
    
    return checkSerialNo

#Creates response of handshake for start operation according to requested serial number
def createStartMessageResponse (reqSerialNo):
    deviceNumber = 0
    startMessage = ""
    
    for i in range(0, len(AMRParams.serialNo)):
        if reqSerialNo == AMRParams.serialNo[i]:
            deviceNumber = i
            AMRParams.deviceNumber = deviceNumber
            print("deviceNumber:" + str(deviceNumber))
    
    if AMRParams.brand[deviceNumber] == "LUNA":
        startMessage = "/LUN5<1>LUN" + str(AMRParams.serialNo[deviceNumber])
    elif AMRParams.brand[deviceNumber] == "KOHLER":
        startMessage =  "/AEL5<1>AEL.TF.21"
        startMessage =  f"/LGZ{AMRParams.baud_to_iec(AMRParams.baudrateInRuntime)}ZMF100AC.M29"
    elif AMRParams.brand[deviceNumber] == "MAKEL":
        startMessage = "/MSY5<1>C500.KMY.2556"
    elif AMRParams.brand[deviceNumber] == "VIKO":
        startMessage = "/VIK5<1>VEMM" + str(AMRParams.serialNo[deviceNumber])
    else:
        startMessage = ""
    startMessage+='\r\n'
    return startMessage

#Inits AMR process
def amrInit():
    global checkUserSerialList
    success = checkUserSerialList()
    return success

#Checks requested serial no for starting to first handshake
def amrSerialListCheckProcess (readBuffer):
    opSuccess = False
    if len(AMRParams.requestedSerialNo) == 0:
        AMRParams.requestedSerialNo = '' # AMRParams.serialNo[0]
        opSuccess = True
    else:
        AMRParams.requestedSerialNo = getSerialNo(readBuffer)
        opSuccess = checkSeriaNoFromSerialList(AMRParams.requestedSerialNo)
    
    return opSuccess

#Checks master query type
def checkAMRQueryType(readBuffer):
    if any([read_out in readBuffer for read_out in READ_OUT_COMMANDS]):
        if DEBUG_AMR_ENABLE:
            print("DEBUG_AMR: ReadOut State...")
        return AMR_STATE.READOUT_PROCESS
    elif "/?" in readBuffer and "!" in readBuffer:
        if DEBUG_AMR_ENABLE:
            print("DEBUG_AMR: Start Process State...")
        return AMR_STATE.START_PROCESS
    elif chr(IEC_MAGIC_BYTES.NCK) == readBuffer[0:1]:
        if DEBUG_AMR_ENABLE:
            print("DEBUG_AMR: Repeat (NCK) State...")
        return AMR_STATE.REPEAT
    else:
        if DEBUG_AMR_ENABLE:
            print("DEBUG_AMR: Error Process State...")
        return AMR_STATE.ERROR_PROCESS

#Creates Readout Response for Luna Meter
#This format is real data comes from one of test meters.
#User can change this format and values
def createLunaReadoutResponse():
    readoutStr =  ''' 0.0.0(70000130)
        0.9.1(10:29:08)
        0.9.2(19-05-10)
        0.9.5(5)
        1.6.0(000.000*kW)(00-00-00,00:00)
        1.8.0(062846.236*kWh)
        1.8.1(039647.863*kWh)
        1.8.2(016924.378*kWh)
        1.8.3(006273.995*kWh)
        1.8.4(000000.000*kWh)
        5.8.0(014172.850*kVArh)
        8.8.0(004422.501*kVArh)
        96.1.3(15-07-02)
        96.2.5(15-07-02)
        96.6.1(1)
        96.70(18-04-06,16:05)
        96.71(19-05-01,00:00)(01)
        1.6.0*1(002.076*kW)(16-12-05,12:45)
        1.6.0*2(005.656*kW)(16-09-02,16:15)
        1.8.0*1(062846.236*kWh)
        1.8.0*2(062846.236*kWh)
        1.8.1*1(039647.863*kWh)
        1.8.1*2(039647.863*kWh)
        1.8.2*1(016924.378*kWh)
        1.8.2*2(016924.378*kWh)
        1.8.3*1(006273.995*kWh)
        1.8.3*2(006273.995*kWh)
        1.8.4*1(000000.000*kWh)
        1.8.4*2(000000.000*kWh)
        5.8.0*1(014172.850*kVArh)
        5.8.0*2(014172.850*kVArh)
        8.8.0*1(004422.501*kVArh)
        8.8.0*2(004422.501*kVArh)
        96.71*1(19-04-01,00:00)(01)
        96.71*2(19-03-01,00:00)(01)
        0.1.0(45)
        96.77.4(02)
        96.77.5(43)
        96.7.0(60)
        96.7.1(03)
        96.7.2(30)
        96.7.3(34)
        0.1.2*1(19-05-01,00:00)
        0.1.2*2(19-04-01,00:00)
        96.77.4*1(18-04-07,10:46,00-00-00,00:00)
        96.77.4*2(16-12-05,11:21,16-12-05,12:23)
        96.77.5*1(16-08-20,22:26,16-08-21,05:33)
        96.77.5*2(16-08-17,22:14,16-08-18,05:51)
        96.77.0*1(19-05-10,10:01,19-05-10,10:11)
        96.77.0*2(19-05-09,20:14,19-05-10,08:37)
        96.77.1*1(19-05-04,14:49,19-05-04,15:51)
        96.77.1*2(19-05-04,13:42,19-05-04,14:41)
        96.77.2*1(19-05-10,10:11,00-00-00,00:00)
        96.77.2*2(19-05-10,08:37,19-05-10,10:03)
        96.77.3*1(19-05-10,10:11,00-00-00,00:00)
        96.77.3*2(19-05-10,08:37,19-05-10,10:03)
        0.8.0(15*min)
        96.2.2(15-07-02,11:40)
        96.50(06001700220099999999999999999999)
        96.51(06001700220099999999999999999999)
        96.52(06001700220099999999999999999999)
        96.60(31230000)
        96.61(31230000)
        96.62(31230000)
        32.7.0(231.1*V)
        31.7.0(000.000*A)
        33.7.0(+1.00)
        52.7.0(000.0*V)
        51.7.0(000.000*A)
        53.7.0( 0.00)
        72.7.0(000.0*V)
        71.7.0(000.000*A)
        73.7.0( 0.00)
        34.7.0(50.0*Hz)
        54.7.0(00.0*Hz)
        74.7.0(00.0*Hz)
        96.80*1(15-07-02,11:43,15-07-02,11:43)
        96.80*2(99-99-99,99:99,99-99-99,99:99)
        96.80(01)
        96.7.5(0969)(02:30:57)!'''

    return readoutStr

#Creates Readout Response for Makel Meter
#This format is real data comes from one of test meters.
#User can change this format and values
def createMakelReadoutResponse():
    readoutStr = '''0.0.0(80099921)
        0.8.0(15*min)
        0.9.1(10:29:26)
        0.9.2(19-05-10)
        0.9.5(5)
        0.1.0(00)
        0.1.2*1(00-00-00,00:00)
        0.1.2*2(00-00-00,00:00)
        0.1.2*3(00-00-00,00:00)
        0.1.2*4(00-00-00,00:00)
        0.1.2*5(00-00-00,00:00)
        0.1.2*6(00-00-00,00:00)
        0.1.2*7(00-00-00,00:00)
        0.1.2*8(00-00-00,00:00)
        0.1.2*9(00-00-00,00:00)
        0.1.2*10(00-00-00,00:00)
        0.1.2*11(00-00-00,00:00)
        0.1.2*12(00-00-00,00:00)
        1.8.0(000000.015*kWh)
        1.8.1(000000.000*kWh)
        1.8.2(000000.015*kWh)
        1.8.3(000000.000*kWh)
        1.8.4(000000.000*kWh)
        1.8.0*1(000000.000*kWh)
        1.8.1*1(000000.000*kWh)
        1.8.2*1(000000.000*kWh)
        1.8.3*1(000000.000*kWh)
        1.8.4*1(000000.000*kWh)
        1.8.0*2(000000.000*kWh)
        1.8.1*2(000000.000*kWh)
        1.8.2*2(000000.000*kWh)
        1.8.3*2(000000.000*kWh)
        1.8.4*2(000000.000*kWh)
        5.8.0(000000.008*kVArh)
        5.8.0*1(000000.000*kVArh)
        5.8.0*2(000000.000*kVArh)
        8.8.0(000000.004*kVArh)
        8.8.0*1(000000.000*kVArh)
        8.8.0*2(000000.000*kVArh)
        1.6.0(000.060*kW)(18-12-13,17:15)
        1.6.0*1(000.000*kW)(00-00-00,00:00)
        1.6.0*2(000.000*kW)(00-00-00,00:00)
        31.7.0(00.007*A)
        51.7.0(00.002*A)
        71.7.0(00.003*A)
        32.7.0(230.35*V)
        52.7.0(001.46*V)
        72.7.0(001.49*V)
        96.90(00-00-00,00:00)
        96.6.1(1)
        96.1.3(17-09-19)
        96.2.5(17-09-19)
        96.2.2(17-09-19,00:17)
        96.50(06001700220099999999999999999999)
        96.51(06001700220099999999999999999999)
        96.52(06001700220099999999999999999999)
        96.60(31230000)
        96.61(31230000)
        96.62(31230000)
        96.70(00-00-00,00:00)
        96.71(00-00-00,00:00)(00)
        96.71*1(00-00-00,00:00)(00)
        96.71*2(00-00-00,00:00)(00)
        96.7.0(38)
        96.77.0*1(19-05-10,10:03,19-05-10,10:14)
        96.77.0*2(19-05-09,20:17,19-05-10,08:40)
        96.7.1(00)
        96.77.1*1(00-00-00,00:00,00-00-00,00:00)
        96.77.1*2(00-00-00,00:00,00-00-00,00:00)
        96.7.2(02)
        96.77.2*1(18-12-12,20:19,99-99-99,99:99)
        96.77.2*2(18-04-08,10:58,18-12-12,20:08)
        96.7.3(01)
        96.77.3*1(18-04-08,10:58,99-99-99,99:99)
        96.77.3*2(00-00-00,00:00,00-00-00,00:00)
        96.77.4(01)
        96.77.4*1(18-04-08,10:58,99-99-99,99:99)
        96.77.4*2(00-00-00,00:00,00-00-00,00:00)
        96.77.5(01)
        96.77.5*1(18-12-13,17:09,99-99-99,99:99)
        96.77.5*2(00-00-00,00:00,00-00-00,00:00)
        96.77.6(00)
        96.77.6*1(00-00-00,00:00,00-00-00,00:00)
        96.77.6*2(00-00-00,00:00,00-00-00,00:00)
        !'''
    return readoutStr

#Creates Readout Response for Viko Meter
#This format is real data comes from one of test meters.
#User can change this format and values
def createVikoReadoutResponse():
    readoutStr = '''0.0.0(01405959)
        0.8.0(15*min)
        0.9.1(10:39:08)
        0.9.2(12-01-11)
        0.9.5(3)
        1.6.0(000.000*kW)(00-00-00,00:00)
        1.6.0*1(000.000*kW)(00-00-00,00:00)
        1.6.0*2(000.000*kW)(00-00-00,00:00)
        1.6.0*3(000.000*kW)(00-00-00,00:00)
        1.6.0*4(000.000*kW)(00-00-00,00:00)
        1.6.0*5(000.000*kW)(00-00-00,00:00)
        1.6.0*6(000.000*kW)(00-00-00,00:00)
        1.6.0*7(000.000*kW)(00-00-00,00:00)
        1.6.0*8(000.000*kW)(00-00-00,00:00)
        1.6.0*9(000.000*kW)(00-00-00,00:00)
        1.6.0*10(000.000*kW)(00-00-00,00:00)
        1.6.0*11(000.000*kW)(00-00-00,00:00)
        1.6.0*12(000.000*kW)(00-00-00,00:00)
        1.8.0(00000.000*kWh)
        1.8.1(00000.000*kWh)
        1.8.1*1(00000.000*kWh)
        1.8.1*2(00000.000*kWh)
        1.8.1*3(00000.000*kWh)
        1.8.1*4(00000.000*kWh)
        1.8.1*5(00000.000*kWh)
        1.8.1*6(00000.000*kWh)
        1.8.1*7(00000.000*kWh)
        1.8.1*8(00000.000*kWh)
        1.8.1*9(00000.000*kWh)
        1.8.1*10(00000.000*kWh)
        1.8.1*11(00000.000*kWh)
        1.8.1*12(00000.000*kWh)
        1.8.2(00000.000*kWh)
        1.8.2*1(00000.000*kWh)
        1.8.2*2(00000.000*kWh)
        1.8.2*3(00000.000*kWh)
        1.8.2*4(00000.000*kWh)
        1.8.2*5(00000.000*kWh)
        1.8.2*6(00000.000*kWh)
        1.8.2*7(00000.000*kWh)
        1.8.2*8(00000.000*kWh)
        1.8.2*9(00000.000*kWh)
        1.8.2*10(00000.000*kWh)
        1.8.2*11(00000.000*kWh)
        1.8.2*12(00000.000*kWh)
        1.8.3(00000.000*kWh)
        1.8.3*1(00000.000*kWh)
        1.8.3*2(00000.000*kWh)
        1.8.3*3(00000.000*kWh)
        1.8.3*4(00000.000*kWh)
        1.8.3*5(00000.000*kWh)
        1.8.3*6(00000.000*kWh)
        1.8.3*7(00000.000*kWh)
        1.8.3*8(00000.000*kWh)
        1.8.3*9(00000.000*kWh)
        1.8.3*10(00000.000*kWh)
        1.8.3*11(00000.000*kWh)
        1.8.3*12(00000.000*kWh)
        1.8.4(00000.000*kWh)
        1.8.4*1(00000.000*kWh)
        1.8.4*2(00000.000*kWh)
        1.8.4*3(00000.000*kWh)
        1.8.4*4(00000.000*kWh)
        1.8.4*5(00000.000*kWh)
        1.8.4*6(00000.000*kWh)
        1.8.4*7(00000.000*kWh)
        1.8.4*8(00000.000*kWh)
        1.8.4*9(00000.000*kWh)
        1.8.4*10(00000.000*kWh)
        1.8.4*11(00000.000*kWh)
        1.8.4*12(00000.000*kWh)
        96.1.3(11-11-16)
        96.2.2(11-11-16,16:07)
        96.2.5(11-11-16)
        96.50(06001700220099999999999999999999)
        96.51(06001700220099999999999999999999)
        96.52(06001700220099999999999999999999)
        96.6.1(1)
        96.60(12399999)
        96.61(12399999)
        96.62(12399999)
        96.70(00-00-00,00:00)
        96.71(00-00-00,00:00)(00)
        96.71*1(00-00-00,00:00)(00)
        96.71*2(00-00-00,00:00)(00)
        96.71*3(00-00-00,00:00)(00)
        96.71*4(00-00-00,00:00)(00)
        96.71*5(00-00-00,00:00)(00)
        96.71*6(00-00-00,00:00)(00)
        96.71*7(00-00-00,00:00)(00)
        96.71*8(00-00-00,00:00)(00)
        96.71*9(00-00-00,00:00)(00)
        96.71*10(00-00-00,00:00)(00)
        96.71*11(00-00-00,00:00)(00)
        96.71*12(00-00-00,00:00)(00)
        96.97(01*hour)
        96.98(0)
        32.7.0(00218.837*V)
        31.7.0(00000.000*A)
        21.7.0(00000.001*kW)
        33.7.0(00000.396)
        14.7.0(00050.115*Hz)
        !'''
    return readoutStr

#Creates Readout Response for Kohler Meter
#This format is real data comes from one of test meters.
#User can change this format and values
def createKohlerReadoutResponse():
    readoutStr = '''
0.0.0(21005763) 
0.1.2*1(19-04-01,00:00)
0.1.2*2(19-01-01,00:00)
0.1.2*3(18-08-01,00:00)
0.1.2*4(18-07-01,00:00)
0.1.2*5(18-06-01,00:00)
0.1.2*6(18-04-01,00:00)
0.1.2*7(18-03-01,00:00)
0.1.2*8(18-02-01,00:00)
0.1.2*9(18-01-01,00:00)
0.1.2*10(17-12-01,00:00)
0.1.2*11(17-11-01,00:00)
0.1.2*12(17-10-01,00:00)
0.2.0(KOM21005763 CRC:0x269D A1 Nov 21 2016)
0.8.0(15*min)
0.9.1(18:30:35)
0.9.2(19-04-25)
0.9.5(4)
1.6.0(000.000*kW)(19-04-01,00:00)
1.6.0*1(000.000*kW)(19-01-01,00:00)
1.6.0*2(000.000*kW)(18-08-01,00:00)
1.6.0*3(000.000*kW)(18-07-01,00:00)
1.6.0*4(000.000*kW)(18-06-01,00:00)
1.6.0*5(000.000*kW)(18-04-01,00:00)
1.6.0*6(000.000*kW)(18-03-01,00:00)
1.6.0*7(000.000*kW)(18-02-01,00:00)
1.6.0*8(000.000*kW)(18-01-01,00:00)
1.6.0*9(000.000*kW)(17-12-01,00:00)
1.6.0*10(000.000*kW)(17-11-01,00:00)
1.6.0*11(000.000*kW)(17-10-01,00:00)
1.6.0*12(000.000*kW)(17-09-01,00:00)
1.8.0(000000.000*kWh)
1.8.0*1(000000.000*kWh)
1.8.0*2(000000.000*kWh)
1.8.0*3(000000.000*kWh)
1.8.0*4(000000.000*kWh)
1.8.0*5(000000.000*kWh)
1.8.0*6(000000.000*kWh)
1.8.0*7(000000.000*kWh)
1.8.0*8(000000.000*kWh)
1.8.0*9(000000.000*kWh)
1.8.0*10(000000.000*kWh)
1.8.0*11(000000.000*kWh)
1.8.0*12(000000.000*kWh)
1.8.1(000000.000*kWh)
1.8.1*1(000000.000*kWh)
1.8.1*2(000000.000*kWh)
1.8.1*3(000000.000*kWh)
1.8.1*4(000000.000*kWh)
1.8.1*5(000000.000*kWh)
1.8.1*6(000000.000*kWh)
1.8.1*7(000000.000*kWh)
1.8.1*8(000000.000*kWh)
1.8.1*9(000000.000*kWh)
1.8.1*10(000000.000*kWh)
1.8.1*11(000000.000*kWh)
1.8.1*12(000000.000*kWh)
1.8.2(000000.000*kWh)
1.8.2*1(000000.000*kWh)
1.8.2*2(000000.000*kWh)
1.8.2*3(000000.000*kWh)
1.8.2*4(000000.000*kWh)
1.8.2*5(000000.000*kWh)
1.8.2*6(000000.000*kWh)
1.8.2*7(000000.000*kWh)
1.8.2*8(000000.000*kWh)
1.8.2*9(000000.000*kWh)
1.8.2*10(000000.000*kWh)
1.8.2*11(000000.000*kWh)
1.8.2*12(000000.000*kWh)
1.8.3(000000.000*kWh)
1.8.3*1(000000.000*kWh)
1.8.3*2(000000.000*kWh)
1.8.3*3(000000.000*kWh)
1.8.3*4(000000.000*kWh)
1.8.3*5(000000.000*kWh)
1.8.3*6(000000.000*kWh)
1.8.3*7(000000.000*kWh)
1.8.3*8(000000.000*kWh)
1.8.3*9(000000.000*kWh)
1.8.3*10(000000.000*kWh)
1.8.3*11(000000.000*kWh)
1.8.3*12(000000.000*kWh)
1.8.4(000000.000*kWh)
1.8.4*1(000000.000*kWh)
1.8.4*2(000000.000*kWh)
1.8.4*3(000000.000*kWh)
1.8.4*4(000000.000*kWh)
1.8.4*5(000000.000*kWh)
1.8.4*6(000000.000*kWh)
1.8.4*7(000000.000*kWh)
1.8.4*8(000000.000*kWh)
1.8.4*9(000000.000*kWh)
1.8.4*10(000000.000*kWh)
1.8.4*11(000000.000*kWh)
1.8.4*12(000000.000*kWh)
2.6.0(000.004*kW)(19-04-25,15:00)
2.6.0*1(000.004*kW)(19-03-20,02:30)
2.6.0*2(000.000*kW)(18-08-01,00:00)
2.6.0*3(000.004*kW)(18-07-02,21:30)
2.6.0*4(000.004*kW)(18-06-22,13:45)
2.6.0*5(000.004*kW)(18-05-19,17:00)
2.6.0*6(000.004*kW)(18-03-01,22:00)
2.6.0*7(000.004*kW)(18-02-03,09:45)
2.6.0*8(000.004*kW)(18-01-04,13:15)
2.6.0*9(000.004*kW)(17-12-05,12:45)
2.6.0*10(000.004*kW)(17-11-04,19:30)
2.6.0*11(000.004*kW)(17-10-04,04:00)
2.6.0*12(000.004*kW)(17-09-13,03:00)
2.8.0(000000.043*MWh)
2.8.0*1(000000.042*kWh)
2.8.0*2(000000.041*kWh)
2.8.0*3(000000.041*kWh)
2.8.0*4(000000.037*kWh)
2.8.0*5(000000.035*kWh)
2.8.0*6(000000.034*kWh)
2.8.0*7(000000.029*kWh)
2.8.0*8(000000.024*kWh)
2.8.0*9(000000.022*kWh)
2.8.0*10(000000.017*kWh)
2.8.0*11(000000.011*kWh)
2.8.0*12(000000.005*kWh)
2.8.1(000000.022*kWh)
2.8.1*1(000000.021*kWh)
2.8.1*2(000000.021*kWh)
2.8.1*3(000000.021*kWh)
2.8.1*4(000000.020*kWh)
2.8.1*5(000000.019*kWh)
2.8.1*6(000000.018*kWh)
2.8.1*7(000000.016*kWh)
2.8.1*8(000000.012*kWh)
2.8.1*9(000000.010*kWh)
2.8.1*10(000000.008*kWh)
2.8.1*11(000000.005*kWh)
2.8.1*12(000000.003*kWh)
 2.8.2(000000.006*kWh)
 2.8.2*1(000000.006*kWh)
 2.8.2*2(000000.006*kWh)
 2.8.2*3(000000.006*kWh)
 2.8.2*4(000000.005*kWh)
 2.8.2*5(000000.004*kWh)
 2.8.2*6(000000.004*kWh)
 2.8.2*7(000000.003*kWh)
2.8.2*8(000000.002*kWh)
2.8.2*9(000000.002*kWh)
2.8.2*10(000000.001*kWh)
2.8.2*11(000000.000*kWh)
2.8.2*12(000000.000*kWh)
2.8.3(000000.015*kWh)
2.8.3*1(000000.015*kWh)
2.8.3*2(000000.014*kWh)
2.8.3*3(000000.014*kWh)
2.8.3*4(000000.012*kWh)
2.8.3*5(000000.012*kWh)
2.8.3*6(000000.012*kWh)
2.8.3*7(000000.010*kWh)
2.8.3*8(000000.010*kWh)
2.8.3*9(000000.010*kWh)
2.8.3*10(000000.008*kWh)
2.8.3*11(000000.006*kWh)
2.8.3*12(000000.002*kWh)
2.8.4(000000.000*kWh)
2.8.4*1(000000.000*kWh)
2.8.4*2(000000.000*kWh)
2.8.4*3(000000.000*kWh)
2.8.4*4(000000.000*kWh)
2.8.4*5(000000.000*kWh)
2.8.4*6(000000.000*kWh)
2.8.4*7(000000.000*kWh)
2.8.4*8(000000.000*kWh)
2.8.4*9(000000.000*kWh)
2.8.4*10(000000.000*kWh)
2.8.4*11(000000.000*kWh)
2.8.4*12(000000.000*kWh)
21.7.0(000.000*kW)
22.7.0(000.000*kW)
31.7.0(000.001*A)
31.7.1(200.00%)
31.7.2(50Hz,00000,00000,00000,00000,00000,00000,00000,00000)
32.7.0(233.07*V)
32.7.1(002.00%)
32.7.2(50Hz,17598,00013,00235,00000,00182,00008,00187,00005)
33.7.0(-1.000)
34.7.0(050.000*Hz)
35.7.1(004.00%)
41.7.0(000.000*kW)
42.7.0(000.000*kW)
5.8.0(000000.000*kVarh)
5.8.0*1(000000.000*kVarh)
5.8.0*2(000000.000*kVarh)
5.8.0*3(000000.000*kVarh)
5.8.0*4(000000.000*kVarh)
5.8.0*5(000000.000*kVarh)
5.8.0*6(000000.000*kVarh)
5.8.0*7(000000.000*kVarh)
5.8.0*8(000000.000*kVarh)
5.8.0*9(000000.000*kVarh)
5.8.0*10(000000.000*kVarh)
5.8.0*11(000000.000*kVarh)
5.8.0*12(000000.000*kVarh)
5.8.1(000000.000*kVarh)
5.8.1*1(000000.000*kVarh)
5.8.1*2(000000.000*kVarh)
5.8.1*3(000000.000*kVarh)
5.8.1*4(000000.000*kVarh)
5.8.1*5(000000.000*kVarh)
5.8.1*6(000000.000*kVarh)
5.8.1*7(000000.000*kVarh)
5.8.1*8(000000.000*kVarh)
5.8.1*9(000000.000*kVarh)
5.8.1*10(000000.000*kVarh)
5.8.1*11(000000.000*kVarh)
5.8.1*12(000000.000*kVarh)
5.8.2(000000.000*kVarh)
5.8.2*1(000000.000*kVarh)
5.8.2*2(000000.000*kVarh)
5.8.2*3(000000.000*kVarh)
5.8.2*4(000000.000*kVarh)
5.8.2*5(000000.000*kVarh)
5.8.2*6(000000.000*kVarh)
5.8.2*7(000000.000*kVarh)
5.8.2*8(000000.000*kVarh)
5.8.2*9(000000.000*kVarh)
5.8.2*10(000000.000*kVarh)
5.8.2*11(000000.000*kVarh)
5.8.2*12(000000.000*kVarh)
5.8.3(000000.000*kVarh)
5.8.3*1(000000.000*kVarh)
5.8.3*2(000000.000*kVarh)
5.8.3*3(000000.000*kVarh)
5.8.3*4(000000.000*kVarh)
5.8.3*5(000000.000*kVarh)
5.8.3*6(000000.000*kVarh)
5.8.3*7(000000.000*kVarh)
5.8.3*8(000000.000*kVarh)
5.8.3*9(000000.000*kVarh)
5.8.3*10(000000.000*kVarh)
5.8.3*11(000000.000*kVarh)
5.8.3*12(000000.000*kVarh)
5.8.4(000000.000*kVarh)
5.8.4*1(000000.000*kVarh)
5.8.4*2(000000.000*kVarh)
5.8.4*3(000000.000*kVarh)
5.8.4*4(000000.000*kVarh)
5.8.4*5(000000.000*kVarh)
5.8.4*6(000000.000*kVarh)
5.8.4*7(000000.000*kVarh)
5.8.4*8(000000.000*kVarh)
5.8.4*9(000000.000*kVarh)
5.8.4*10(000000.000*kVarh)
5.8.4*11(000000.000*kVarh)
5.8.4*12(000000.000*kVarh)
51.7.0(000.002*A)
51.7.1(200.00%)
51.7.2(50Hz,00000,00000,00000,00000,00000,00000,00000,00000)
52.7.0(000.00*V)
52.7.1(000.00%)
52.7.2(50Hz,00000,00000,00000,00000,00000,00000,00000,00000)
53.7.0( 0.000)
54.7.0(000.000*Hz)
55.7.1(000.00%)
6.8.0(000000.000*kVarh)
6.8.0*1(000000.000*kVarh)
6.8.0*2(000000.000*kVarh)
6.8.0*3(000000.000*kVarh)
6.8.0*4(000000.000*kVarh)
6.8.0*5(000000.000*kVarh)
6.8.0*6(000000.000*kVarh)
6.8.0*7(000000.000*kVarh)
6.8.0*8(000000.000*kVarh)
6.8.0*9(000000.000*kVarh)
6.8.0*10(000000.000*kVarh)
6.8.0*11(000000.000*kVarh)
6.8.0*12(000000.000*kVarh)
6.8.1(000000.000*kVarh)
6.8.1*1(000000.000*kVarh)
6.8.1*2(000000.000*kVarh)
6.8.1*3(000000.000*kVarh)
6.8.1*4(000000.000*kVarh)
6.8.1*5(000000.000*kVarh)
6.8.1*6(000000.000*kVarh)
6.8.1*7(000000.000*kVarh)
6.8.1*8(000000.000*kVarh)
6.8.1*9(000000.000*kVarh)
6.8.1*10(000000.000*kVarh)
6.8.1*11(000000.000*kVarh)
6.8.1*12(000000.000*kVarh)
6.8.2(000000.000*kVarh)
6.8.2*1(000000.000*kVarh)
6.8.2*2(000000.000*kVarh)
6.8.2*3(000000.000*kVarh)
6.8.2*4(000000.000*kVarh)
6.8.2*5(000000.000*kVarh)
6.8.2*6(000000.000*kVarh)
6.8.2*7(000000.000*kVarh)
6.8.2*8(000000.000*kVarh)
6.8.2*9(000000.000*kVarh)
6.8.2*10(000000.000*kVarh)
6.8.2*11(000000.000*kVarh)
6.8.2*12(000000.000*kVarh)
6.8.3(000000.000*kVarh)
6.8.3*1(000000.000*kVarh)
6.8.3*2(000000.000*kVarh)
6.8.3*3(000000.000*kVarh)
6.8.3*4(000000.000*kVarh)
6.8.3*5(000000.000*kVarh)
6.8.3*6(000000.000*kVarh)
6.8.3*7(000000.000*kVarh)
6.8.3*8(000000.000*kVarh)
6.8.3*9(000000.000*kVarh)
6.8.3*10(000000.000*kVarh)
6.8.3*11(000000.000*kVarh)
6.8.3*12(000000.000*kVarh)
6.8.4(000000.000*kVarh)
6.8.4*1(000000.000*kVarh)
6.8.4*2(000000.000*kVarh)
6.8.4*3(000000.000*kVarh)
6.8.4*4(000000.000*kVarh)
6.8.4*5(000000.000*kVarh)
6.8.4*6(000000.000*kVarh)
6.8.4*7(000000.000*kVarh)
6.8.4*8(000000.000*kVarh)
6.8.4*9(000000.000*kVarh)
6.8.4*10(000000.000*kVarh)
6.8.4*11(000000.000*kVarh)
6.8.4*12(000000.000*kVarh)
61.7.0(000.000*kW)
62.7.0(000.000*kW)
7.8.0(000000.007*kVarh)
7.8.0*1(000000.007*kVarh)
7.8.0*2(000000.007*kVarh)
7.8.0*3(000000.007*kVarh)
7.8.0*4(000000.006*kVarh)
7.8.0*5(000000.006*kVarh)
7.8.0*6(000000.006*kVarh)
7.8.0*7(000000.005*kVarh)
7.8.0*8(000000.003*kVarh)
7.8.0*9(000000.003*kVarh)
7.8.0*10(000000.002*kVarh)
7.8.0*11(000000.001*kVarh)
7.8.0*12(000000.000*kVarh)
7.8.1(000000.003*kVarh)
7.8.1*1(000000.003*kVarh)
7.8.1*2(000000.003*kVarh)
7.8.1*3(000000.003*kVarh)
7.8.1*4(000000.002*kVarh)
7.8.1*5(000000.002*kVarh)
7.8.1*6(000000.002*kVarh)
7.8.1*7(000000.002*kVarh)
7.8.1*8(000000.001*kVarh)
7.8.1*9(000000.001*kVarh)
7.8.1*10(000000.000*kVarh)
7.8.1*11(000000.000*kVarh)
7.8.1*12(000000.000*kVarh)
7.8.2(000000.002*kVarh)
7.8.2*1(000000.002*kVarh)
7.8.2*2(000000.002*kVarh)
7.8.2*3(000000.002*kVarh)
7.8.2*4(000000.002*kVarh)
7.8.2*5(000000.002*kVarh)
7.8.2*6(000000.002*kVarh)
7.8.2*7(000000.001*kVarh)
7.8.2*8(000000.001*kVarh)
7.8.2*9(000000.001*kVarh)
7.8.2*10(000000.001*kVarh)
7.8.2*11(000000.000*kVarh)
7.8.2*12(000000.000*kVarh)
7.8.3(000000.002*kVarh)
7.8.3*1(000000.002*kVarh)
7.8.3*2(000000.002*kVarh)
7.8.3*3(000000.002*kVarh)
7.8.3*4(000000.002*kVarh)
7.8.3*5(000000.002*kVarh)
7.8.3*6(000000.002*kVarh)
7.8.3*7(000000.002*kVarh)
7.8.3*8(000000.001*kVarh)
7.8.3*9(000000.001*kVarh)
7.8.3*10(000000.001*kVarh)
7.8.3*11(000000.001*kVarh)
7.8.3*12(000000.000*kVarh)
7.8.4(000000.000*kVarh)
7.8.4*1(000000.000*kVarh)
7.8.4*2(000000.000*kVarh)
7.8.4*3(000000.000*kVarh)
7.8.4*4(000000.000*kVarh)
7.8.4*5(000000.000*kVarh)
7.8.4*6(000000.000*kVarh)
7.8.4*7(000000.000*kVarh)
7.8.4*8(000000.000*kVarh)
7.8.4*9(000000.000*kVarh)
7.8.4*10(000000.000*kVarh)
7.8.4*11(000000.000*kVarh)
7.8.4*12(000000.000*kVarh)
71.7.0(000.001*A)
71.7.1(200.00%)
71.7.2(50Hz,00000,00000,00000,00000,00000,00000,00000,00000)
72.7.0(000.00*V)
72.7.1(000.00%)
72.7.2(50Hz,00000,00000,00000,00000,00000,00000,00000,00000)
73.7.0( 0.000)
74.7.0(000.000*Hz)
75.7.1(000.00%)
8.8.0(000000.065*kVarh)
8.8.0*1(000000.065*kVarh)
8.8.0*2(000000.061*kVarh)
8.8.0*3(000000.061*kVarh)
8.8.0*4(000000.056*kVarh)
8.8.0*5(000000.053*kVarh)
8.8.0*6(000000.050*kVarh)
8.8.0*7(000000.041*kVarh)
8.8.0*8(000000.030*kVarh)
8.8.0*9(000000.027*kVarh)
8.8.0*10(000000.022*kVarh)
8.8.0*11(000000.016*kVarh)
8.8.0*12(000000.008*kVarh)
8.8.1(000000.028*kVarh)
8.8.1*1(000000.028*kVarh)
8.8.1*2(000000.027*kVarh)
8.8.1*3(000000.027*kVarh)
8.8.1*4(000000.025*kVarh)
8.8.1*5(000000.024*kVarh)
8.8.1*6(000000.023*kVarh)
8.8.1*7(000000.019*kVarh)
8.8.1*8(000000.014*kVarh)
8.8.1*9(000000.011*kVarh)
8.8.1*10(000000.009*kVarh)
8.8.1*11(000000.006*kVarh)
8.8.1*12(000000.002*kVarh)
8.8.2(000000.014*kVarh)
8.8.2*1(000000.014*kVarh)
8.8.2*2(000000.014*kVarh)
8.8.2*3(000000.014*kVarh)
8.8.2*4(000000.013*kVarh)
8.8.2*5(000000.012*kVarh)
8.8.2*6(000000.012*kVarh)
8.8.2*7(000000.011*kVarh)
8.8.2*8(000000.009*kVarh)
8.8.2*9(000000.009*kVarh)
8.8.2*10(000000.008*kVarh)
8.8.2*11(000000.006*kVarh)
8.8.2*12(000000.004*kVarh)
8.8.3(000000.023*kVarh)
8.8.3*1(000000.023*kVarh)
8.8.3*2(000000.020*kVarh)
8.8.3*3(000000.020*kVarh)
8.8.3*4(000000.018*kVarh)
8.8.3*5(000000.017*kVarh)
8.8.3*6(000000.015*kVarh)
8.8.3*7(000000.011*kVarh)
8.8.3*8(000000.007*kVarh)
8.8.3*9(000000.007*kVarh)
8.8.3*10(000000.005*kVarh)
8.8.3*11(000000.004*kVarh)
8.8.3*12(000000.002*kVarh)
8.8.4(000000.000*kVarh)
8.8.4*1(000000.000*kVarh)
8.8.4*2(000000.000*kVarh)
8.8.4*3(000000.000*kVarh)
8.8.4*4(000000.000*kVarh)
8.8.4*5(000000.000*kVarh)
8.8.4*6(000000.000*kVarh)
8.8.4*7(000000.000*kVarh)
8.8.4*8(000000.000*kVarh)
8.8.4*9(000000.000*kVarh)
8.8.4*10(000000.000*kVarh)
8.8.4*11(000000.000*kVarh)
8.8.4*12(000000.000*kVarh)
96.1.3(17-07-18)
96.2.2(17-07-18,10:55)
96.2.5(17-07-18)
96.50(00000600170022009999999999999999)
96.51(00000600170022009999999999999999)
96.52(00000600170022009999999999999999)
96.6.1(1)
96.60(31230000)
96.61(31230000)
96.62(31230000)
96.7.0(71)
96.7.1(00)
96.7.2(00)
96.7.3(00)
96.70(00-00-00,00:00)
96.71(19-04-01,00:00)(01)
96.71*1(19-01-01,00:00)(01)
96.71*2(18-08-01,00:00)(01)
96.71*3(18-07-01,00:00)(01)
96.71*4(18-06-01,00:00)(01)
96.71*5(18-05-17,13:12)(02)
96.71*6(00-00-00,00:00)(00)
96.71*7(00-00-00,00:00)(00)
96.71*8(00-00-00,00:00)(00)
96.71*9(00-00-00,00:00)(00)
96.71*10(00-00-00,00:00)(00)
96.71*11(00-00-00,00:00)(00)
96.71*12(00-00-00,00:00)(00)
96.77.0*1(19-04-25,15:55,19-04-25,15:57)
96.77.0*2(19-04-25,15:49,19-04-25,15:52)
96.77.0*3(19-04-25,13:59,19-04-25,14:13)
96.77.0*4(19-04-24,16:54,19-04-25,13:30)
96.77.0*5(19-04-19,19:47,19-04-24,11:32)
96.77.0*6(19-04-18,15:42,19-04-19,08:56)
96.77.0*7(19-04-17,17:26,19-04-18,09:40)
96.77.0*8(19-03-23,16:52,19-04-17,10:34)
96.77.0*9(18-12-18,15:46,19-03-15,09:39)
96.77.0*10(18-07-18,08:39,18-12-18,14:36)
96.77.1*1(00-00-00,00:00,00-00-00,00:00)
96.77.1*2(00-00-00,00:00,00-00-00,00:00)
96.77.1*3(00-00-00,00:00,00-00-00,00:00)
96.77.1*4(00-00-00,00:00,00-00-00,00:00)
96.77.1*5(00-00-00,00:00,00-00-00,00:00)
96.77.1*6(00-00-00,00:00,00-00-00,00:00)
96.77.1*7(00-00-00,00:00,00-00-00,00:00)
96.77.1*8(00-00-00,00:00,00-00-00,00:00)
96.77.1*9(00-00-00,00:00,00-00-00,00:00)
96.77.1*10(00-00-00,00:00,00-00-00,00:00)
96.77.2*1(00-00-00,00:00,00-00-00,00:00)
96.77.2*2(00-00-00,00:00,00-00-00,00:00)
96.77.2*3(00-00-00,00:00,00-00-00,00:00)
96.77.2*4(00-00-00,00:00,00-00-00,00:00)
96.77.2*5(00-00-00,00:00,00-00-00,00:00)
96.77.2*6(00-00-00,00:00,00-00-00,00:00)
96.77.2*7(00-00-00,00:00,00-00-00,00:00)
96.77.2*8(00-00-00,00:00,00-00-00,00:00)
96.77.2*9(00-00-00,00:00,00-00-00,00:00)
96.77.2*10(00-00-00,00:00,00-00-00,00:00)
96.77.3*1(00-00-00,00:00,00-00-00,00:00)
96.77.3*2(00-00-00,00:00,00-00-00,00:00)
96.77.3*3(00-00-00,00:00,00-00-00,00:00)
96.77.3*4(00-00-00,00:00,00-00-00,00:00)
96.77.3*5(00-00-00,00:00,00-00-00,00:00)
96.77.3*6(00-00-00,00:00,00-00-00,00:00)
96.77.3*7(00-00-00,00:00,00-00-00,00:00)
96.77.3*8(00-00-00,00:00,00-00-00,00:00)
96.77.3*9(00-00-00,00:00,00-00-00,00:00)
96.77.3*10(00-00-00,00:00,00-00-00,00:00)
96.77.4(00)
96.77.4*1(00-00-00,00:00,00-00-00,00:00)
96.77.4*2(00-00-00,00:00,00-00-00,00:00)
96.77.4*3(00-00-00,00:00,00-00-00,00:00)
96.77.4*4(00-00-00,00:00,00-00-00,00:00)
96.77.4*5(00-00-00,00:00,00-00-00,00:00)
96.77.4*6(00-00-00,00:00,00-00-00,00:00)
96.77.4*7(00-00-00,00:00,00-00-00,00:00)
96.77.4*8(00-00-00,00:00,00-00-00,00:00)
96.77.4*9(00-00-00,00:00,00-00-00,00:00)
96.77.4*10(00-00-00,00:00,00-00-00,00:00)
96.77.5(00)
96.77.5*1(00-00-00,00:00,00-00-00,00:00)
96.77.5*2(00-00-00,00:00,00-00-00,00:00)
96.77.5*3(00-00-00,00:00,00-00-00,00:00)
96.77.5*4(00-00-00,00:00,00-00-00,00:00)
96.77.5*5(00-00-00,00:00,00-00-00,00:00)
96.77.5*6(00-00-00,00:00,00-00-00,00:00)
96.77.5*7(00-00-00,00:00,00-00-00,00:00)
96.77.5*8(00-00-00,00:00,00-00-00,00:00)
96.77.5*9(00-00-00,00:00,00-00-00,00:00)
96.77.5*10(00-00-00,00:00,00-00-00,00:00)
96.77.6(00)
96.77.6*1(00-00-00,00:00,00-00-00,00:00)
96.77.6*2(00-00-00,00:00,00-00-00,00:00)
96.77.6*3(00-00-00,00:00,00-00-00,00:00)
96.77.6*4(00-00-00,00:00,00-00-00,00:00)
96.77.6*5(00-00-00,00:00,00-00-00,00:00)
96.77.6*6(00-00-00,00:00,00-00-00,00:00)
96.77.6*7(00-00-00,00:00,00-00-00,00:00)
96.77.6*8(00-00-00,00:00,00-00-00,00:00)
96.77.6*9(00-00-00,00:00,00-00-00,00:00)
96.77.6*10(00-00-00,00:00,00-00-00,00:00)
96.93(0)
97.97.0(00)
97.97.0*1(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*2(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*3(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*4(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*5(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*6(00-00-00,00:00,00-00-00,00:00,00)
97.97.0*7(00-00-00,00:00,00-00-00,00:00,00)
!
<3>}'''
    return readoutStr

def createNoBrandReadoutResponse():
    readoutStr = '''F.F(00)
1.8.0(000052.337*kWh)
2.8.0(000376.432*kWh)
3.8.0(000145.875*kvarh)
4.8.0(000010.724*kvarh)
15.8.0(000428.769*kWh)
32.7(231*V)
52.7(231*V)
72.7(231*V)
31.7(00.000*A)
51.7(00.000*A)
71.7(00.000*A)
13.7(-.--)
14.7(50.0*Hz)
C.1.0(40799390)
0.0(40799390 )
C.1.1( )
0.2.0(M29)
16.7(000.00*kW)
131.7(000.00*kVAr)
C.5.0(6402)
C.7.0(0064)
!
'''
    return chr(IEC_MAGIC_BYTES.STX) + readoutStr + chr(IEC_MAGIC_BYTES.ETX) + chr(IEC_MAGIC_BYTES.BCC_LGZ)

#Conditions the readout message according to meter brand names
def createReadoutMessage(meterBrand):
    if meterBrand == "LUNA":
        return(createLunaReadoutResponse())
    elif meterBrand == "MAKEL":
        return(createMakelReadoutResponse())
    elif meterBrand == "VIKO":
        return(createVikoReadoutResponse())
    elif meterBrand == "KOHLER":
        return(createKohlerReadoutResponse())
    else:
        # no brand
        return(createNoBrandReadoutResponse())
