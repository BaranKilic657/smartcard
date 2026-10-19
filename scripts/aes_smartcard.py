import time

from smartcard.ATR import ATR
from smartcard.CardRequest import CardRequest
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers


class SmartCard:
    CLA_BL = 0x80
    CLA_APP = 0x88

    INS_DECRYPT = 0x10
    INS_GET_RESPONSE = 0xC0

    SW_SUCCESS = (0x90, 0x00)
    SW_BOOTLOADER = (0x61, 0x02)
    SW_WRONG_LENGTH = (0x67, 0x00)
    SW_WRONG_P1P2 = (0x6A, 0x86)
    SW_INVALID_INS = (0x6D, 0x00)
    SW_INVALID_CLA = (0x6E, 0x00)

    def __init__(self) -> None:
        self._connection = None

    def connect(self, enter_app: bool = True) -> None:
        # Detect the smart card based on the content of the ATR (card-centric approach)
        try:
            r = readers()
            if not r:
                print("No readers found")
                raise self.NoReaderError()

            # Cardrequest returns a cardservice
            self.cs = CardRequest(readers=r, timeout=5).waitforcard()
            if self.cs is None:
                raise self.ScConnectionError("Cardservice returned None")
            self._connection = self.cs.connection
            self._connection.connect()

            self._atr = self._connection.getATR()
            if not ATR(self._atr).isT0Supported():
                raise self.ScConnectionError("Card does not support T0 protocol.")
            if len(self._atr) < 16:
                raise self.NoCardIdError()
            self.card_id = bytes(self._atr[4:16])
        except TimeoutError as err:
            raise self.TimeoutError(err)
        if enter_app:
            time.sleep(0.5)  # Required to ensure card left bootloader mode

    def _check_status_words(self, sw1, sw2) -> None:
        # Compare status words against expected values
        match (sw1, sw2):
            case self.SW_SUCCESS:
                ...
            case self.SW_BOOTLOADER:
                ...
            case (0x61, 0x10):
                ...
            case self.SW_WRONG_LENGTH:
                raise self.WrongLengthError()
            case self.SW_WRONG_P1P2:
                raise self.WrongParameterError()
            case self.SW_INVALID_INS:
                raise self.InvalidInsError()
            case self.SW_INVALID_CLA:
                raise self.InvalidClaError()
            case _:
                raise self.StatusWordError(
                    f"Got unknown status words: SW1 0x{sw1:02x} SW2 0x{sw2:02x}"
                )

    def _transmit(self, command: list[int]) -> list[int]:
        if self._connection is None:
            raise self.CardConnectionError()
        response, sw1, sw2 = self._connection.transmit(command)
        self._check_status_words(sw1, sw2)
        return response

    def decrypt(self, ciphertext) -> list[int]:
        # Format the command to be sent to the card:
        DECRYPT = [
            self.CLA_APP,
            self.INS_DECRYPT,
            0x00,
            0x00,
            len(ciphertext),
        ] + ciphertext
        GET_RESPONSE = [self.CLA_APP, self.INS_GET_RESPONSE, 0x00, 0x00, 0x10]
        try:
            self._transmit(DECRYPT)
        except CardConnectionException as err:
            raise self.CardConnectionError(err)
        return self._transmit(GET_RESPONSE)

    def disconnect(self) -> None:
        if self._connection:
            self._connection.disconnect()

    class SmartCardError(Exception): ...

    class NoReaderError(SmartCardError): ...

    class TimeoutError(SmartCardError): ...

    class ScConnectionError(SmartCardError): ...

    class NoCardIdError(SmartCardError): ...

    class CardConnectionError(SmartCardError): ...

    class StatusWordError(SmartCardError): ...

    class WrongLengthError(StatusWordError): ...

    class WrongParameterError(StatusWordError): ...

    class InvalidInsError(StatusWordError): ...

    class InvalidClaError(StatusWordError): ...
