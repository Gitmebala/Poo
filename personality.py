"""
Poo's personality.

She is not the same character on day one as she is a month in. Her bond grows
from being cared for, and it moves her through four stages:

    SHY       she likes you but hides it, easily flustered
    WARMING   starting to trust you, peeks more, small gestures
    PLAYFUL   confident, cheeky, wants to mess about
    DEVOTED   openly adores you, watches for you, misses you

The stage biases which idle acts she picks and which things she says, so the
change is felt through behaviour rather than announced.

Her name for you is HER_NAME. She uses it sparingly on purpose - a name that
appears constantly stops meaning anything.
"""
import random
import time

HER_NAME = "Moonpie"

SHY, WARMING, PLAYFUL, DEVOTED = 0, 1, 2, 3
STAGE_NAMES = {SHY: "shy", WARMING: "warming", PLAYFUL: "playful", DEVOTED: "devoted"}

# Bond thresholds. Bond rises ~0.02 per pet plus a trickle for time together,
# so these land at roughly: warming within a first sitting, playful after a day
# or two, devoted after a few days of regular attention. Slower than this and
# she never gets to show her warmest side.
STAGE_AT = [0.0, 2.0, 7.0, 16.0]


def stage_for(bond):
    s = SHY
    for i, t in enumerate(STAGE_AT):
        if bond >= t:
            s = i
    return s


# How strongly each stage prefers each kind of idle act. Missing entries use 1.0.
ACT_BIAS = {
    SHY: {"wave": 0.15, "hum": 0.4, "hop": 0.5, "spin": 0.3,
          "shy_hide": 2.6, "peek": 2.2, "look": 1.4},
    WARMING: {"wave": 0.7, "hum": 1.0, "hop": 1.0, "shy_hide": 1.2,
              "peek": 1.4, "look": 1.2},
    PLAYFUL: {"wave": 1.4, "hop": 2.0, "wiggle": 1.9, "spin": 1.8,
              "hum": 1.3, "shy_hide": 0.4, "tease": 2.2},
    DEVOTED: {"wave": 1.8, "watch_you": 2.6, "hum": 1.5, "wiggle": 1.2,
              "shy_hide": 0.2, "hop": 1.0, "cuddle": 2.4},
}


def bias(stage, act_name):
    return ACT_BIAS.get(stage, {}).get(act_name, 1.0)


# ---------------------------------------------------------------- dialogue --
# {} is replaced with her name for you. Lines are deliberately short: they are
# drawn as small text above her head, not speech bubbles of prose.
LINES = {
    "first_meeting": {
        SHY: ["oh! hello", "...hi", "*hides*"],
    },
    "greet": {
        SHY: ["...hi", "oh, you're here", "*peeks*"],
        WARMING: ["hi!", "you came back", "hello!"],
        PLAYFUL: ["hi hi hi!", "there you are!", "missed me?"],
        DEVOTED: ["hi {}!", "you're back!", "there you are {}"],
    },
    "long_absence": {
        SHY: ["...you were gone", "oh. hi again"],
        WARMING: ["I waited", "you're back!"],
        PLAYFUL: ["where WERE you", "finally!"],
        DEVOTED: ["I missed you {}", "I waited for you", "don't go so long"],
    },
    "petted": {
        SHY: ["...", "*blush*", "eep"],
        WARMING: ["hehe", "that's nice", "*happy*"],
        PLAYFUL: ["more!", "hehe again!", "yesss"],
        DEVOTED: ["I love you", "*melts*", "again please {}"],
    },
    "tickled": {
        SHY: ["ah-! eep", "hehe stop"],
        WARMING: ["hehehe", "that tickles!"],
        PLAYFUL: ["HEHEHE", "no fair!", "hehe!"],
        DEVOTED: ["hehehe {}!", "you're silly", "hehe!"],
    },
    "shy_moment": {
        SHY: ["*hides*", "...", "eep"],
        WARMING: ["*shy*", "hehe"],
        PLAYFUL: ["stoppp", "*giggles*"],
        DEVOTED: ["*melts*", "you're sweet"],
    },
    "sleepy": {
        SHY: ["...sleepy", "*yawn*"],
        WARMING: ["*yawn*", "so sleepy"],
        PLAYFUL: ["not tired... *yawn*", "five more minutes"],
        DEVOTED: ["stay with me {}", "*yawn* g'night", "sleepy..."],
    },
    "lonely": {
        SHY: ["...", "*waits*"],
        WARMING: ["hello?", "*looks around*"],
        PLAYFUL: ["heyyy", "I'm bored!", "play?"],
        DEVOTED: ["I miss you", "{}?", "come back?"],
    },
    "happy": {
        SHY: ["*happy*", "hehe"],
        WARMING: ["yay!", "hehe!"],
        PLAYFUL: ["WOO", "best day!", "yay!"],
        DEVOTED: ["I'm so happy", "love you {}", "yay!"],
    },
    "morning": {
        SHY: ["...morning", "*sleepy blink*"],
        WARMING: ["morning!", "you're up!"],
        PLAYFUL: ["MORNING!", "up up up!"],
        DEVOTED: ["good morning {}", "morning! *snuggles*"],
    },
    "night": {
        SHY: ["...goodnight", "*curls up*"],
        WARMING: ["night night", "sleep well"],
        PLAYFUL: ["nooo don't sleep", "goodnight!"],
        DEVOTED: ["goodnight {}", "sweet dreams", "stay warm"],
    },
    "dizzy": {
        SHY: ["@_@", "oof"],
        WARMING: ["@_@ dizzy", "woah"],
        PLAYFUL: ["AGAIN!", "@_@ wheee"],
        DEVOTED: ["@_@", "carefulll"],
    },
    "thrown": {
        SHY: ["eep!", "!"],
        WARMING: ["woah!", "eek"],
        PLAYFUL: ["WHEEE", "again!"],
        DEVOTED: ["waaah", "catch me!"],
    },
}

# One-off moments. Each fires once ever, keyed in memory.
MILESTONES = [
    ("first_day",   lambda m: m.get("sessions", 0) >= 1,      "nice to meet you"),
    ("ten_pets",    lambda m: m.get("pets", 0) >= 10,         "you're kind to me"),
    ("hundred_pets", lambda m: m.get("pets", 0) >= 100,       "you always come back"),
    ("week",        lambda m: m.get("seconds_together", 0) >= 3600 * 3,
     "I like it here with you"),
    ("bonded",      lambda m: m.get("bond", 0) >= STAGE_AT[DEVOTED], "you're my favourite"),
]


def line(kind, stage, chance=1.0):
    """Pick something for her to say, or None if she stays quiet."""
    if random.random() > chance:
        return None
    pools = LINES.get(kind)
    if not pools:
        return None
    # fall back down the stages if this one has nothing written for it
    for s in range(stage, -1, -1):
        if s in pools:
            return random.choice(pools[s]).replace("{}", HER_NAME)
    return None


def due_milestone(memory):
    """Return (key, text) for the first unearned milestone she now qualifies for."""
    done = memory.setdefault("milestones", [])
    for key, test, text in MILESTONES:
        if key not in done and test(memory):
            done.append(key)
            return key, text
    return None


def greeting_kind(hours_away, sessions):
    if sessions <= 1:
        return "first_meeting"
    if hours_away >= 10:
        return "long_absence"
    hour = time.localtime().tm_hour
    if 5 <= hour < 11:
        return "morning"
    if hour >= 22 or hour < 5:
        return "night"
    return "greet"
