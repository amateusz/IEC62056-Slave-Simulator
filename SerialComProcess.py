#Serial Communication .py file includes all serial port init, read and partial send
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

#Global Functions
from AMRProcess import amrSerialListCheckProcess
from AMRProcess import createStartMessageResponse
from AMRProcess import checkAMRQueryType
from AMRProcess import createReadoutMessage
from AMRProcess import IEC_MAGIC_BYTES, AMR_STATE
from SystemFunc import waitUntilEnterPressed

#Global Class Objects
from AMRProcess import AMRParams

#Constant Definitions
DEBUG_SERIAL_COM = 1
INVALID_DEVICE_NUMBER = -1

#Inits serial com port with user configured params.
def serialInit():
        global serialPort 
        try:
                serialPort = serial.Serial(AMRParams.comPortName, 
                                          AMRParams.baudrateInStart, 
                                          timeout = None,
                                          bytesize = AMRParams.dataBit,
                                          parity = AMRParams.parity,
                                          stopbits = AMRParams.stopBit)
                
                print(serialPort.name)
        except:
                print("ERROR_COMM: Please check Com Port!")
                waitUntilEnterPressed()

#Decodes string to UTF-8 Format
def decodeStr(inputStr):
    return inputStr.decode('utf-8')

#Encodes string to Bytes format for serial comm. application
def encodeStr(inputStr):
    return str.encode(inputStr)

#Periodic Read Event Threads
def readFromSerialPort ():
    state = None
    while True:
        
        readBuffer = serialPort.read_until(expected=b'\r\n')
        
        if decodeStr(readBuffer) != '':
                state_pre = state
                state = checkAMRQueryType(decodeStr(readBuffer))
                if state == AMR_STATE.REPEAT:
                        state = state_pre

                if state == AMR_STATE.START_PROCESS:
                        opSuccess = amrSerialListCheckProcess(decodeStr(readBuffer))
                        if opSuccess:
                                writeToSerialPort(createStartMessageResponse(AMRParams.requestedSerialNo))
                                time.sleep(0.01)
                elif state == AMR_STATE.READOUT_PROCESS:
                        assert(readBuffer[0] == IEC_MAGIC_BYTES.ACK or chr(readBuffer[0]) == '.')
                        
                        if AMRParams.deviceNumber != INVALID_DEVICE_NUMBER and AMRParams.enable[AMRParams.deviceNumber]:
                                brand = AMRParams.brand[AMRParams.deviceNumber]
                        else:
                                print("WARNING: invalid device number")
                                brand = None
                        
                        change_baudrate = True
                        
                        serialPort.flush()

                        if change_baudrate:
                                serialPort.baudrate = AMRParams.baudrateInRuntime
                                print(f"INFO: setting baud {serialPort.baudrate} (assuming HHD respects meter's preference)")
                                
                        time.sleep(1.100) # legal delay (<1.5s)
                        print("INFO: sent readout start!")
                        writeToSerialPort(createReadoutMessage(brand))
                        # this is so dumb, but pyserial's write is actually not blocking!!!
                        # this block leaves too early, while the actuall write is still pending (esp on baud 600)
                        # and changes the baud back to 300, while still sending. SO DUMB of pyserial!
                        # implement manual delay, don't trust .out_waiting, .write_timeout, .flush()
                        bytes_per_sec = serialPort.baudrate/7
                        time_to_write = len(createReadoutMessage(brand)) / bytes_per_sec * 1.5 # it takes longer than theory
                        time.sleep(time_to_write)
                        print("INFO: sent readout done")
                        
                        if change_baudrate:
                                serialPort.baudrate = AMRParams.baudrateInStart
                                
                        AMRParams.deviceNumber = INVALID_DEVICE_NUMBER
                else:
                        print("ERROR_COMM: Unexpected State is occured in runtime!")

        time.sleep(0.01)

#Inits Read Event Thread
def readFromSerialPortThreadInit():
    receiveEvent = threading.Thread(target=readFromSerialPort)
    receiveEvent.start()

#Splits bulks string data to n parts defined by size of s and chunksize
def split_chunks(s, chunksize):
    pos = 0
    while(pos != -1):
        new_pos = s.rfind(" ", pos, pos+chunksize)
        if(new_pos == pos):
            new_pos += chunksize # force split in word
        yield s[pos:new_pos]
        pos = new_pos


#Writes data to serial port. 
#Bulk String data manupulation is implemented
def writeToSerialPort(sendStr):
        partialSendSize = 2000

        strLen = len(sendStr)
        if strLen <= partialSendSize:
                for line in sendStr.splitlines():
                        payload = encodeStr(line) 
                        if len(payload) == 1 and ord(payload) in (_ for _ in IEC_MAGIC_BYTES):
                                # print('send byte: ', end='')
                                pass
                        elif len(payload) == 2 and payload[0] == IEC_MAGIC_BYTES.ETX:
                                # ETX + BCC sequence
                                pass
                        else:
                                payload += b'\r\n'
                                # print(f'send line: ', end='')
                        # print(payload)
                        serialPort.write(payload)
        else:
                myList = list(split_chunks(sendStr, partialSendSize))
                for i in range (0, len(myList)):
                        serialPort.write(encodeStr(myList[i]))
                        time.sleep(0.1)
