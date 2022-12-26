import datetime
import math
import string
import re

from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                             QScrollArea, QSpinBox, QVBoxLayout, QPushButton)

from helpers import ParserWindow, config, format_time, text_time_to_seconds

WHO_MATCHER   = re.compile(r"^\[(?P<lvl>\d+) (?P<class>\S+)\] (?P<player>\S+)")
ZONE_MATCHER  = re.compile(r"There (is|are) \d+ players? in (?P<zone>.+)\.")
HAIL_MATCHER  = re.compile(r"^Hail, (?P<mobName>\S.+\S)\'s corpse")
SLAIN_MATCHER = re.compile(r"^(?P<mobName>\S.+\S) has been slain by (?P<player>\S.+\S)!")

class Deaths(ParserWindow):
    """Tracks spell casting, duration, and targets by name."""

    def __init__(self):
        super().__init__()
        self.name = 'deaths'
        self.setWindowTitle(self.name.title())
        self.set_title(self.name.title())

        # keep track of which mob dies when
        self.track = {}
        self.playerName = None      # I don't think we have this already
        self.previousLine = ""

    def parse(self, timestamp, text):
        """
        Parse:
        - death messages from mobs
          - You have slain orc pawn
          - orc pawn has been slain by Soandso
        - hail orc pawn's corpse messages

        The 'hail' messages trigger an update to Discord
        """

        mobName    = None
        killerName = "unknown"
        
        # print("parsing {0}:{1}".format(timestamp, text))

        # parsing 2022-12-23 14:35:32.747433:You have slain orc pawn!
        if text[:14] == 'You have slain':
            mobName = text[15:-1]
            if self.playerName:
                killerName = self.playerName
            else:
                killerName = "unknown"
            print("1 {0} slain on {1} by {2}".format(mobName, timestamp, killerName))

        # parsing 2022-12-23 14:37:08.647091:a fire beetle has been slain by Sergeant Slate!
        elif "has been slain by" in text:
            if SLAIN_MATCHER.match(text):
                mobName    = SLAIN_MATCHER.match(text).groupdict()['mobName']
                killerName = SLAIN_MATCHER.match(text).groupdict()['player']
                print("2 {0} slain on {1} by {2}".format(mobName, timestamp, killerName))

        # parsing 2022-12-23 20:34:59.759560:[16 Paladin] Sildiin (High Elf)
        # parsing 2022-12-23 20:34:59.759560:There are 88 players in East Commonlands.
        elif ZONE_MATCHER.match(text) and WHO_MATCHER.match(self.previousLine):
            self.playerName = WHO_MATCHER.match(self.previousLine).groupdict()['player']
            print("I am {0}".format(self.playerName))

        # did we register a kill?
        if mobName:
            # register with latest timestamp
            self.track[mobName] = { 'timestamp': timestamp, 'killer': killerName }
            # when a Hail Soandso's corpse is seen, this timestamp will be sent
            # print("track:")
            # print(self.track)

        # parsing 2022-12-23 14:29:25.076714:You say, 'Hail, a decaying skeleton's corpse'
        if text[:15] == 'You say, \'Hail,' and text[-7:-1] == 'corpse':
            mobName = text[16:-10]
            # print("{0} hailed on {1}".format(mobName, timestamp))

            # if we have a registered death timestamp then we use that instead of the time of the
            # 'hail'
            if mobName in self.track:
                print("1 sending: {0} died on {1} killed by {2}".format(
                    mobName, 
                    self.track[mobName]['timestamp'],
                    self.track[mobName]['killer'],
                ))
            else:
                print("2 sending: {0} died on {1} killed by {2}".format(
                    mobName,
                    timestamp,
                    "unknown"
                ))

        self.previousLine = text
