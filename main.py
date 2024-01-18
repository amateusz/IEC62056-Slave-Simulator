#Main .py file includes all initilization and runtime functions of AMR System
__author__  = "Serbay Ozkan"
__version__ = "1.0.0"
__email__   = "serbay.ozkan@hotmail.com"
__status__  = "Development"

#Import Python Library Modules
import os 
import sys

#Global Functions
from JSONParser       import parseAMRParamsFromJSONFile
from SerialComProcess import serialInit
from SerialComProcess import readFromSerialPortThreadInit
from AMRProcess       import amrInit

def main():
    #Parses AMRParams.json file
    parseAMRParamsFromJSONFile()

    #Inits all serial comm. layer
    serialInit()

    #Inits AMR Serial List Check Operation
    amrInit()

    #Calls periodically read event to handle master requests
    readFromSerialPortThreadInit()

process = None

if __name__ == '__main__':
    main()
else:
    import multiprocessing

    def start():
        global process
        if not process:
            process = multiprocessing.Process(target=main)

        if not process.is_alive():
            process.start()

    def stop():
        global process
        process.terminate()
        process.join()
        process.close() # free-up resources
        process = None

