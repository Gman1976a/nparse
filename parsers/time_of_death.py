import datetime
import calendar
import math
import string
import re

from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar,
                             QScrollArea, QSpinBox, QVBoxLayout, QPushButton)

from helpers import ParserWindow, config, format_time, text_time_to_seconds
from discord import SyncWebhook

WHO_MATCHER   = re.compile(r"^(AFK )*\[(?P<lvl>\d+) (?P<class>\S+)\] (?P<player>\S+)")
ZONE_MATCHER  = re.compile(r"There (is|are) \d+ players? in (?P<zone>.+)\.")
HAIL_MATCHER  = re.compile(r"^Hail, (?P<mobName>\S.+\S)\'s corpse")
SLAIN_MATCHER = re.compile(r"^(?P<mobName>\S.+\S) has been slain by (?P<player>\S.+\S)!")

DAYS_MATCHER  = re.compile(r"(?P<days>\d+)\s*days")
HOURS_MATCHER = re.compile(r"(?P<hours>\d+)\s*hour")
MINS_MATCHER = re.compile(r"(?P<minutes>\d+)\s*min")

class TimeOfDeath(ParserWindow):
    """Tracks spell casting, duration, and targets by name."""

    def __init__(self):
        super().__init__()
        self.name = 'time_of_death'
        self.setWindowTitle(self.name.title())
        self.set_title(self.name.title())

        # keep track of which mob dies when
        self.track = {}
        self.playerName = "unknown"      # I don't think we have this already
        self.zoneName   = None
        self.previousLine = ""

        # read known timers
        self.npcRespawnTimers = read_npc_respawn_timers()

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

        # parsing 2022-12-23 20:34:59.759560:[16 Paladin] Soandso (High Elf)
        # parsing 2022-12-23 20:34:59.759560:There are 88 players in East Commonlands.
        elif ZONE_MATCHER.match(text) and ZONE_MATCHER.match(text).groupdict()['zone'] != 'EverQuest' and WHO_MATCHER.match(self.previousLine):
            # triggered by "/who" command for this zone only
            self.playerName = WHO_MATCHER.match(self.previousLine).groupdict()['player']
            self.zoneName = ZONE_MATCHER.match(text).groupdict()['zone']
            print("I am {0} in zone {1}".format(self.playerName, self.zoneName))

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
                epoch_time = self.logTimeToUnixSeconds(self.track[mobName]['timestamp'])
                message = "{0} died on <t:{1}> killed by {2}.".format(
                    mobName, 
                    epoch_time,
                    self.track[mobName]['killer'],
                )
            else:
                # we only know of the 'Hail' log message, no known time of death
                epoch_time = self.logTimeToUnixSeconds(timestamp)
                message = "{0} corpse hailed by {1} on <t:{2}> killed by {3}.".format(
                    mobName,
                    self.playerName,
                    epoch_time,
                    "unknown"
                )

            if self.zoneName is not None:
                message += " In zone {0}.".format(self.zoneName)
            
            # add respawn info to the message.
            if mobName in self.npcRespawnTimers:
                message += " Respawn time: {0}".format(self.npcRespawnTimers[mobName]['respawn_time'])
                respawn_in_seconds = convert_to_seconds(self.npcRespawnTimers[mobName]['respawn_time'])
                if convert_to_seconds(self.npcRespawnTimers[mobName]['variance']) != 0:
                    message += " with variance {0}".format(self.npcRespawnTimers[mobName]['variance'])
                    variance_in_seconds = convert_to_seconds(self.npcRespawnTimers[mobName]['variance'])
                    message += ". Mob will respawn between <t:{0}> and <t:{1}>".format(
                        epoch_time + respawn_in_seconds - variance_in_seconds,
                        epoch_time + respawn_in_seconds + variance_in_seconds,
                    )
                    message += ". Which is between <t:{0}:R> and <t:{1}:R>".format(
                        epoch_time + respawn_in_seconds - variance_in_seconds,
                        epoch_time + respawn_in_seconds + variance_in_seconds,
                    )
                else:
                    message += ". Mob will respawn on <t:{0}>".format(
                        epoch_time + respawn_in_seconds
                    )
                    message += ". Which is in <t:{0}:R>".format(
                        epoch_time + respawn_in_seconds
                    )
            else:
                message += " No respawn timers known by sender."

            if config.data['time_of_death']['discord_webhook_url']:
                # print("sending to "+config.data['deaths']['discord_webhook_url'])
                try:
                    webhook = SyncWebhook.from_url(config.data['time_of_death']['discord_webhook_url'])
                    webhook.send(message)
                except ValueError as e:
                    print("wrong webhook URL")
            else:
                print("No discord webhook URL configured in settings")

        self.previousLine = text

    def logTimeToUnixSeconds(self, timestamp: datetime.datetime) -> int:
        delta = datetime.datetime.now()-datetime.datetime.utcnow() 
        timestamp = timestamp - delta
        return calendar.timegm(timestamp.timetuple())

def read_npc_respawn_timers():
    """ Returns a dictionary of NPC timers by k, v ->.. """
    
    npcs = {}
    with open('data/npcs/respawn_time.txt') as npc_file:
        for line in npc_file:
            if line[0] == "#":
                continue
            values = line.strip().split(';')
            name = values[0]
            respawn_time = values[1]
            variance = values[2]
            # we expect the respawn time in this format: mobname;respawn;variance
            # Lord Nagafen;7 days;8 hours

            # convert times to seconds
            # respawnInSeconds = convert_to_seconds(respawnTime)
            # varianceInSeconds = convert_to_seconds(variance)
            # print("{0} {1} {2}".format(name, respawnTime, variance))
            npcs[name] = { 'respawn_time': respawn_time, 'variance': variance }
    return npcs

def convert_to_seconds(text: str) -> int:
    seconds = 0
    if DAYS_MATCHER.match(text):
        seconds += int(DAYS_MATCHER.match(text).groupdict()['days']) * 86400
    if HOURS_MATCHER.match(text):
        seconds += int(HOURS_MATCHER.match(text).groupdict()['hours']) * 3600
    if MINS_MATCHER.match(text):
        seconds += int(MINS_MATCHER.match(text).groupdict()['minutes']) * 60
    return seconds