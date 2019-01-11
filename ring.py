from ring_doorbell import Ring
import time
import fhem
import logging
from thread import start_new_thread, allocate_lock


# CONFIG
ring_user = 'user@domain.com'
ring_pass = 'password'
fhem_ip   = '127.0.0.1'
fhem_port = 7072 # Telnet Port
log_level = logging.DEBUG
fhem_path = '/opt/fhem/www/ring/' # for video downloads
POLLS     = 2 # Poll every x seconds

# LOGGING
logger = logging.getLogger('ring_doorbell.doorbot')
logger.setLevel(log_level)

# create file handler which logs even debug messages
fh = logging.FileHandler('ring.log')
fh.setLevel(logging.DEBUG)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
fh.setFormatter(formatter)

# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)

logger = logging.getLogger('fhem_ring')
logger.setLevel(log_level)
logger.addHandler(ch)
logger.addHandler(fh)


# Connecting to RING.com
myring = Ring(ring_user, ring_pass)

fh = fhem.Fhem(fhem_ip, fhem_port)

def sendFhem(str):
    logger.debug("sending: " + str)
    global fh
    fh.send_cmd(str)

def askFhemForReading(dev, reading):
    logger.debug("ask fhem for reading " + reading + " from device " + dev)
    return fh.get_dev_reading(dev, reading)

def askFhemForAttr(dev, attr, default):
    logger.debug("ask fhem for attribute "+attr+" from device "+dev+" (default: "+default+")")
    fh.send_cmd('{AttrVal("'+dev+'","'+attr+'","'+default+'")}')
    data = fh.sock.recv(32000)
    return data

def setRing(str, dev):
    sendFhem('set Ring_' + dev.name.replace(" ","") + ' ' + str)

def attrRing(str, dev):
    sendFhem('attr Ring_' + dev.name.replace(" ","") + ' ' + str)

def srRing(str, dev):
    sendFhem('setreading Ring_' + dev.name.replace(" ","") + ' ' + str)

num_threads = 0
thread_started = False
lock = allocate_lock()

def getDeviceInfo(dev):
    dev.update()
    logger.info("Updating device data for device '"+dev.name+"' in FHEM...")
    srRing('account ' + str(dev.account_id), dev)
    srRing('address ' + str(dev.address), dev) 
    srRing('family ' + str(dev.family), dev) 
    srRing('id ' + str(dev.id), dev) 
    srRing('name ' + str(dev.name), dev) 
    srRing('timezone ' + str(dev.timezone), dev) 
    srRing('doorbellType ' + str(dev.existing_doorbell_type), dev)
    srRing('battery ' + str(dev.battery_life), dev)
    srRing('ringVolume ' + str(dev.volume), dev)
    srRing('connectionStatus ' + str(dev.connection_status), dev) 
    srRing('WifiName ' + str(dev.wifi_name), dev) 
    srRing('WifiRSSI ' + str(dev.wifi_signal_strength), dev) 
    

def pollDevices():
    logger.info("Polling for events.")
    global devs

    i=0
    while 1:
        for k, poll_device in devs.items():
            logger.debug("Polling for events with '" + poll_device.name + "'.")
            if poll_device.check_alerts() and poll_device.alert:
                dev = devs[poll_device.alert.get('doorbot_id')]
                logger.info("Alert detected at '" + dev.name + "'.")
                logger.debug("Alert detected at '" + dev.name + "' via '" + poll_device.name + "'.")
                alertDevice(dev,poll_device.alert)
            time.sleep(POLLS)
        i+=1
        if i>600:
            break

def alertDevice(dev,alert):
    srRing('lastAlertDeviceID ' + str(dev.id), dev)
    srRing('lastAlertDeviceAccountID ' + str(dev.account_id), dev)
    srRing('lastAlertDeviceName ' + str(dev.name), dev)
    srRing('lastAlertSipTo ' + str(alert.get('sip_to')), dev)
    srRing('lastAlertSipToken ' + str(alert.get('sip_token')), dev)
    
    lastAlertID = alert.get('id')
    lastAlertKind = alert.get('kind')
    
    if (lastAlertKind == 'ding') or (lastAlertKind == 'motion'):
        lastHistoryID = dev.history(limit=1,kind=lastAlertKind)[0]['id']
        
        #Wait and check history until new alert is added
        i=0
        while lastHistoryID != lastAlertID:
            logger.debug("Wait and check history until new alert is added lastHistoryID != lastAlertID")
            logger.debug(" lastHistoryID:"+str(lastHistoryID))
            logger.debug(" lastAlertID:"+str(lastAlertID))
            time.sleep(POLLS)
            lastHistoryID = dev.history(limit=1,kind=lastAlertKind)[0]['id']
            
            i+=1
            if i>60: # break when no history object can be found
                break
                
        if (lastAlertKind == 'ding') and i<=60:
            dev.recording_download(lastAlertID, filename=fhem_path + 'last_ding_video.mp4',override=True)
            srRing('lastDingVideo ' + fhem_path + 'last_ding_video.mp4', dev)
            setRing('ring', dev)
            srRing('lastAlertType ring', dev)
            
        elif (lastAlertKind == 'motion') and i<=60:
            dev.recording_download(lastAlertID, filename=fhem_path + 'last_motion_video.mp4',override=True)
            srRing('lastMotionVideo ' + fhem_path + 'last_motion_video.mp4', dev)
            srRing('lastAlertType motion', dev)
            setRing('motion', dev)  
        
        if i<=60:
            srRing('lastCaptureURL ' + str(dev.recording_url(dev.last_recording_id)), dev)



# GATHERING DEVICES
devs = dict()
poll_device = None
tmp = list(myring.stickup_cams + myring.doorbells)
for t in tmp:
    devs[t.account_id] = t
    # all alerts can be recognized on all devices
    poll_device = t # take one device for polling

logger.info("Found " + str(len(devs)) + " devices.")

# START POLLING DEVICES
count = 1
while count<6:  # try 5 times
    try:
        while 1:
            for k, d in devs.items(): getDeviceInfo(d)
            pollDevices()

    except Exception as inst:
        logger.error("Unexpected error:" + str(inst))
        logger.error("Exception occured. Retrying...")
        time.sleep(5)
        if count == 5:
            raise

        count += 1
