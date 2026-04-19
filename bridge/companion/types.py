"""Protocol enumerations for the MeshCore companion protocol.

Values match meshcore-rs src/packets.rs and src/commands/base.rs exactly.
"""
from __future__ import annotations

from enum import IntEnum


class PacketType(IntEnum):
    """Response packet types — first byte of every radio→app payload."""
    OK                    = 0x00
    ERROR                 = 0x01
    CONTACT_START         = 0x02
    CONTACT               = 0x03
    CONTACT_END           = 0x04
    SELF_INFO             = 0x05
    MSG_SENT              = 0x06
    CONTACT_MSG_RECV      = 0x07
    CHANNEL_MSG_RECV      = 0x08
    CURRENT_TIME          = 0x09
    NO_MORE_MSGS          = 0x0A
    CONTACT_URI           = 0x0B
    BATTERY               = 0x0C
    DEVICE_INFO           = 0x0D
    PRIVATE_KEY           = 0x0E
    DISABLED              = 0x0F
    CONTACT_MSG_RECV_V3   = 0x10
    CHANNEL_MSG_RECV_V3   = 0x11
    CHANNEL_INFO          = 0x12
    SIGN_START            = 0x13
    SIGNATURE             = 0x14
    CUSTOM_VARS           = 0x15
    STATS                 = 0x18
    AUTOADD_CONFIG        = 0x19
    BINARY_REQ            = 0x32
    FACTORY_RESET         = 0x33
    PATH_DISCOVERY        = 0x34
    SET_FLOOD_SCOPE       = 0x36
    SEND_CONTROL_DATA     = 0x37
    ADVERTISEMENT         = 0x80
    PATH_UPDATE           = 0x81
    ACK                   = 0x82
    MESSAGES_WAITING      = 0x83
    RAW_DATA              = 0x84
    LOGIN_SUCCESS         = 0x85
    LOGIN_FAILED          = 0x86
    STATUS_RESPONSE       = 0x87
    LOG_DATA              = 0x88
    TRACE_DATA            = 0x89
    PUSH_CODE_NEW_ADVERT  = 0x8A
    TELEMETRY_RESPONSE    = 0x8B
    BINARY_RESPONSE       = 0x8C
    PATH_DISCOVERY_RESP   = 0x8D
    CONTROL_DATA          = 0x8E
    ADVERT_RESPONSE       = 0x8F
    UNKNOWN               = 0xFF

    @classmethod
    def from_byte(cls, b: int) -> "PacketType":
        try:
            return cls(b)
        except ValueError:
            return cls.UNKNOWN


class CommandType(IntEnum):
    """Command types — first byte of every app→radio payload."""
    APP_START             = 1
    SEND_TXT_MSG          = 2
    SEND_CHANNEL_TXT_MSG  = 3
    GET_CONTACTS          = 4
    GET_DEVICE_TIME       = 5
    SET_DEVICE_TIME       = 6
    SEND_SELF_ADVERT      = 7
    SET_ADVERT_NAME       = 8
    ADD_UPDATE_CONTACT    = 9
    SYNC_NEXT_MESSAGE     = 10
    SET_RADIO_PARAMS      = 11
    SET_RADIO_TX_POWER    = 12
    RESET_PATH            = 13
    SET_ADVERT_LATLON     = 14
    REMOVE_CONTACT        = 15
    SHARE_CONTACT         = 16
    EXPORT_CONTACT        = 17
    IMPORT_CONTACT        = 18
    REBOOT                = 19
    GET_BATT_AND_STORAGE  = 20
    SET_TUNING_PARAMS     = 21
    DEVICE_QUERY          = 22
    EXPORT_PRIVATE_KEY    = 23
    IMPORT_PRIVATE_KEY    = 24
    SEND_RAW_DATA         = 25
    SEND_LOGIN            = 26
    SEND_STATUS_REQ       = 27
    HAS_CONNECTION        = 28
    LOGOUT                = 29
    GET_CONTACT_BY_KEY    = 30
    GET_CHANNEL           = 31
    SET_CHANNEL           = 32
    SIGN_START            = 33
    SIGN_DATA             = 34
    SIGN_FINISH           = 35
    GET_CUSTOM_VARS       = 40
    SET_CUSTOM_VAR        = 41
    SEND_BINARY_REQ       = 50
    SET_FLOOD_SCOPE       = 54


class BinaryReqType(IntEnum):
    STATUS     = 0x01
    KEEPALIVE  = 0x02
    TELEMETRY  = 0x03
    MMA        = 0x04
    ACL        = 0x05
    NEIGHBOURS = 0x06


class LxmfTransport(IntEnum):
    """How a given MeshCore packet type travels over Reticulum/LXMF."""
    INTERNAL   = 0   # bridge-internal — no wire encoding
    ANNOUNCE   = 1   # Reticulum announce
    DIRECT     = 2   # encrypted unicast LXMF
    PROPAGATED = 3   # LXMF store-and-forward
    RECEIPT    = 4   # Reticulum delivery confirmation (transport-layer)


class LxmfDestType(IntEnum):
    NODE    = 0   # meshcore.node.<hash>
    BRIDGE  = 1   # meshcore.bridge.<hash>
    CHANNEL = 2   # meshcore.channel.<hash>
