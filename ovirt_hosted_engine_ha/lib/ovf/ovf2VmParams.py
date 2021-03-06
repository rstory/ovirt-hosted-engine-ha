import sys
from ovirt_hosted_engine_ha.env import constants
import ovfenvelope
import logging

RES_ALLOCATION_NS = \
    'Content/Section/Item/{' \
    'http://schemas.dmtf.org/wbem/wscim/1/cim-schema' \
    '/2/CIM_ResourceAllocationSettingData' \
    '}'

OVF_NS = \
    '{http://schemas.dmtf.org/ovf/envelope/1/}'

RASD_NS = \
    '{http://schemas.dmtf.org/wbem/wscim/1/cim-schema' \
    '/2/CIM_ResourceAllocationSettingData}'


# mimic the ovirt engine enum of DisplayType
# better solution is to let the engine embed
# its enums in the OVF so we're always updated
# or import java classes or do code generation for python
DISPLAY_TYPES = {
    0: 'vnc',  # cirrus
    1: 'qxl',  # qxl
    2: 'vnc'   # vga
}

# ovf device types mapping
DEVICE_TYPE = {
    'scsi': 'disk',
}

NETWORK_INTERFACE_TYPE = {
    0: 'rtl8139_pv',
    1: 'rtl8139',
    2: 'e1000',
    3: 'pv',
    4: 'spaprVlan',
    5: 'pciPassthrough'
}


def text(xmlElement, param):
    subElement = xmlElement.find(param)
    return subElement.text if subElement is not None else None


def diskFromElements(device, diskElement, diskIndex):
    disk = {}
    if diskIndex == 2:
        # 2 is reserved for CDROM
        diskIndex = 3
    disk['index'] = str(diskIndex)
    disk['type'] = text(device, 'Type')
    disk['device'] = text(device, 'Device')
    disk['iface'] = diskElement.attrib[OVF_NS + 'disk-interface'].lower()
    disk['format'] = diskElement.attrib[OVF_NS + 'volume-format'].lower()
    # we must use BLANK because hosted engine VM might start without the pool
    #  being attached
    disk['poolID'] = constants.BLANK_UUID
    disk['domainID'] = text(device, RASD_NS + 'StorageId')
    disk['imageID'] = diskElement.attrib[OVF_NS + 'fileRef'].split('/')[0]
    disk['volumeID'] = diskElement.attrib[OVF_NS + 'fileRef'].split('/')[1]
    disk['deviceId'] = disk['imageID']
    disk['readonly'] = text(device, 'IsReadOnly')
    address = text(device, RASD_NS + 'Address')
    disk['address'] = (
        address.replace("=", ':') if address is not None else None
    )
    disk['bootOrder'] = str(int(text(device, 'BootOrder')) + 1)
    disk['propagateErrors'] = 'off'
    disk['shared'] = 'exclusive'
    return disk


def addDisks(devices, device, tree, index):
    # find corresponding disk element
    for diskElement in tree.findall('Section/Disk'):
        if diskElement.attrib[OVF_NS + 'diskId'] \
                == text(device, RASD_NS + 'InstanceId'):
            devices.append(
                diskFromElements(device, diskElement, index)
            )
            index += 1


def buildDevice(device):
    dev = {}
    dev['type'] = text(device, 'Type')
    dev['device'] = text(device, 'Device')
    dev['deviceId'] = text(device, RASD_NS + 'InstanceId')
    address = text(device, RASD_NS + 'Address')
    dev['address'] = address.replace("=", ':') if address is not None else None
    specParams = device.find(RASD_NS + "SpecParams")
    if specParams is not None:
        dev['specParams'] = specParams
    return dev


def buildCdrom(device):
    cdrom = buildDevice(device)
    cdrom['index'] = '2'
    cdrom['iface'] = 'ide'
    cdrom['address'] = '{ controller:0, target:0,unit:0, bus:1, type:drive}'
    cdrom['readonly'] = 'true'
    cdrom['deviceId'] = '8c3179ac-b322-4f5c-9449-c52e3665e0ae'
    cdrom['path'] = ''
    cdrom['device'] = 'cdrom'
    cdrom['shared'] = 'false'
    cdrom['type'] = 'disk'
    return cdrom


def buildNic(device):
    nic = buildDevice(device)
    nicModel = text(device, RASD_NS + "ResourceSubType")
    if nicModel is not None:
        nic['nicModel'] = NETWORK_INTERFACE_TYPE[int(nicModel)]
    nic['macAddr'] = text(device, RASD_NS + "MACAddress")
    nic['network'] = text(device, RASD_NS + "Connection")
    nic['linkActive'] = text(device, RASD_NS + "Linked")
    if nic['macAddr'] is None or nic['macAddr'] == 'None':
        return None
    return nic


def buildController(device):
    controller = buildDevice(device)
    if controller['device'] == 'scsi':
        controller['model'] = 'virtio-scsi'
    return controller


def buildConsole(device):
    console = buildDevice(device)
    return console


def buildVideo(device):
    video = buildDevice(device)
    video['alias'] = 'video0'
    return video


def addStubs(vmParams):
    """
    Add sections which are mandatory and can't be converted from the OVF

    :param vmParams:
    """
    vmParams['spiceSecureChannels'] = \
        'smain,sdisplay,sinputs,scursor,splayback,srecord,ssmartcard,susbredir'


def toDict(ovf):
    """
    Convert an OVF to a vmConf dictionary

    :param  ovf: the OVF string
    :type ovf: str
    :return: dict to be used to create a new VM using vdsCli
             - See vdsCli#create
    """
    tree = ovfenvelope.etree_.fromstring(ovf)

    vmParams = {}

    # general
    vmParams['vmId'] = tree.find('Content/Section').attrib[OVF_NS + 'id']
    vmParams['vmName'] = text(tree, 'Content/Name')
    vmParams['display'] = DISPLAY_TYPES.get(
        int(text(tree, 'Content/DefaultDisplayType'))
    )
    vmParams['cpuType'] = text(tree, 'Content/CustomCpuName')
    vmParams['emulatedMachine'] = text(tree, 'Content/CustomEmulatedMachine')
    # cpu
    num_of_sockets = int(text(tree, RES_ALLOCATION_NS + 'num_of_sockets'))
    cpu_per_socket = int(text(tree, RES_ALLOCATION_NS + 'cpu_per_socket'))
    vmParams['smp'] = str(num_of_sockets * cpu_per_socket)
    if tree.find(RES_ALLOCATION_NS + 'max_num_of_vcpus') is not None:
        vmParams['maxVCpus'] = \
            text(tree, RES_ALLOCATION_NS + 'max_num_of_vcpus')

    # mem
    # TODO use it to convert memSize
    # unit = text(tree, RES_ALLOCATION_NS + 'AllocationUnits')
    vmParams['memSize'] = text(tree, RES_ALLOCATION_NS + 'VirtualQuantity')

    # devices
    vmParams['devices'] = devices = []
    index = 0  # 2 saved for cdrom
    cdromBuilt = False
    for device in tree.find('Content').iter('Item'):
        if device.find('Type') is not None:
            t = text(device, 'Type')
            if t == 'disk' and text(device, 'Device') == 'disk':
                addDisks(devices, device, tree, index)
            elif t == 'disk' and text(device, 'Device') == 'cdrom' \
                    and not cdromBuilt:
                devices.append(buildCdrom(device))
                cdromBuilt = True
            elif t == 'interface':
                devices.append(buildNic(device))
            elif t == 'controller':
                devices.append(buildController(device))
            elif t == 'console':
                # TODO console device still not supported yet
                pass
            elif t == 'video':
                devices.append(buildVideo(device))
    # filter out invalid devices (marked by None)
    vmParams['devices'] = [dev for dev in devices
                           if dev is not None and dev != 'None']

    addStubs(vmParams)

    # filter out empty values
    return {k: v for k, v in vmParams.iteritems() if v is not None}


def confFromOvf(ovf):
    """

    :param  ovf: path to the OVF file
    :type ovf: str
    :return:  key=value representation of the VM from ovf,
              consumable as a conf file
    """
    vmConf = toDict(ovf)
    devices = vmConf.pop('devices')
    conf = \
        ''.join(
            [('%s=%s\n' % (key, value))
             for key, value in vmConf.items()]
        ) + \
        ''.join(
            [('%s=%s\n' % ('devices',
                           str(item).replace('\'', '').replace(' ', '')))
             for item in devices]
        )
    logging.debug('conf is %s', conf)
    return conf


if __name__ == '__main__':
    print(confFromOvf(open(sys.argv[1], 'r')))


# vim: expandtab tabstop=4 shiftwidth=4
