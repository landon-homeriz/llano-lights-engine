"""What a DJ already knows about well-known party and wedding songs, for the set arranger (Llano PM #23177).

The audio tells the arranger a song's tempo, key and loudness. It cannot tell it that everyone at a
wedding, grandparents to kids, knows every word of "Livin' on a Prayer", or that "Dance Her Home" is
a father-daughter song. This table carries that, written down once:

  year       when the song came out (its era)
  energy     1..10, how hard it pushes a dance floor (1 a quiet ballad, 10 a peak-time anthem)
  sing       0..3, how much a room sings along (3: the whole room knows every word)
  known      0..3, how broadly known across ages (3: grandparents and kids alike)
  tags       hype (a safe all-ages opener for the dancing), slow (a slow dance), line (a line or
             group dance), closer (a big end-of-night sing-along), and the wedding moments it suits:
             first-dance, father-daughter, mother-son, last-dance, exit (the couple's exit song) and
             exit-prep (the big sing-along before the grand exit; BL #12360)

A song missing from the table still arranges, from its tempo and audio alone; the window lets him
mark a sing-along by hand. Values are a DJ's judgment, not measurements.
"""
from __future__ import annotations

from typing import Optional

from .settings_contract import track_key
from .song_match import candidates, norm

# (artist, title, year, energy, sing, known, tags)
CANON: tuple = (
    # --- his wedding folder (Avery & Jordan, 2026-11-12): cocktail hour ---
    ("George Strait", "Amarillo by Morning", 1983, 4, 2, 2, ""),
    ("George Strait", "Here for a Good Time", 2011, 5, 1, 1, ""),
    ("Billy Currington", "Good Directions", 2006, 5, 2, 2, ""),
    ("Josh Turner", "Would You Go With Me", 2006, 4, 1, 1, ""),
    ("Trisha Yearwood", "She's in Love with the Boy", 1991, 5, 2, 2, ""),
    ("Clint Black", "Killin' Time", 1989, 5, 1, 1, ""),
    ("Alabama", "The Closer You Get", 1983, 4, 1, 1, ""),
    ("John Michael Montgomery", "I Love the Way You Love Me", 1993, 3, 1, 1, "slow first-dance"),
    ("Keith Whitley", "When You Say Nothing at All", 1988, 3, 2, 2, "slow first-dance"),
    ("Zac Brown Band", "Chicken Fried", 2008, 5, 3, 2, ""),
    ("Brooks & Dunn", "Red Dirt Road", 2003, 5, 2, 1, ""),
    ("Tim McGraw", "Something Like That", 1999, 6, 3, 2, ""),
    ("Diamond Rio", "Meet in the Middle", 1991, 5, 1, 1, ""),
    ("George Strait", "Check Yes or No", 1995, 6, 3, 2, ""),
    # dinner
    ("Lee Brice", "One of Them Girls", 2020, 5, 1, 1, ""),
    ("Lady A", "American Honey", 2010, 4, 2, 2, ""),
    ("Shenandoah", "Two Dozen Roses", 1989, 5, 1, 1, ""),
    ("Lonestar", "Amazed", 1999, 3, 3, 3, "slow first-dance"),
    ("Kenny Chesney", "She's Got It All", 1997, 4, 1, 1, ""),
    ("Cody Johnson", "Diamond in My Pocket", 2021, 3, 1, 1, "slow first-dance"),
    ("Cody Johnson", "Dance Her Home", 2023, 3, 1, 1, "slow father-daughter"),
    ("Luke Combs", "Beautiful Crazy", 2018, 3, 3, 2, "slow first-dance"),
    ("John Michael Montgomery", "I Swear", 1993, 3, 3, 3, "slow first-dance"),
    ("Tim McGraw", "Just to See You Smile", 1997, 5, 2, 2, ""),
    ("Russell Dickerson", "Yours", 2017, 3, 1, 1, "slow first-dance"),
    ("Eric Church", "Springsteen", 2011, 4, 3, 2, ""),
    ("Cody Johnson", "With You I Am", 2019, 3, 1, 1, "slow first-dance"),
    ("Randy Travis", "Deeper Than the Holler", 1988, 4, 2, 2, ""),
    ("George Strait", "You Look So Good in Love", 1983, 3, 1, 1, "slow first-dance"),
    ("Randy Travis", "Forever and Ever, Amen", 1987, 5, 3, 3, "first-dance"),
    # dancing
    ("DJ Casper", "Cha Cha Slide", 2000, 7, 2, 3, "line hype"),
    ("Travis Tritt", "It's a Great Day to Be Alive", 2000, 6, 3, 2, ""),
    ("Black Eyed Peas", "I Gotta Feeling", 2009, 9, 3, 3, "hype"),
    ("Josh Turner", "Why Don't We Just Dance", 2009, 7, 2, 1, "last-dance"),
    ("ABBA", "Dancing Queen", 1976, 7, 3, 3, "hype"),
    ("Justin Bieber", "Baby", 2010, 7, 3, 2, ""),
    ("Justin Bieber", "Sorry", 2015, 7, 2, 2, ""),
    ("Steve Earle", "Copperhead Road", 1988, 8, 2, 2, "line"),
    ("Luke Bryan", "Play It Again", 2014, 7, 3, 2, ""),
    ("Cupid", "Cupid Shuffle", 2007, 7, 2, 3, "line"),
    ("Journey", "Don't Stop Believin'", 1981, 8, 3, 3, "closer"),
    ("Bon Jovi", "Livin' on a Prayer", 1986, 9, 3, 3, "closer hype"),
    ("Jo Dee Messina", "Bye Bye", 1998, 7, 2, 1, ""),
    ("Brooks & Dunn", "My Maria", 1996, 7, 3, 2, ""),
    ("Darius Rucker", "Wagon Wheel", 2013, 7, 3, 3, "closer"),
    ("Jo Dee Messina", "Heads Carolina, Tails California", 1996, 8, 3, 2, ""),
    ("Alan Jackson", "Good Time", 2008, 8, 2, 2, "line"),
    ("Taylor Swift", "You Belong With Me", 2008, 7, 3, 3, ""),
    ("George Strait", "Write This Down", 1999, 7, 2, 2, ""),
    ("Bryan Adams", "Summer of '69", 1985, 8, 3, 3, "closer"),
    ("Brooks & Dunn", "Boot Scootin' Boogie", 1992, 9, 3, 3, "line hype"),
    ("Kenny Loggins", "Footloose", 1984, 9, 3, 3, "hype"),
    ("Blake Shelton", "Footloose", 2011, 9, 3, 2, "hype"),
    ("Owl City", "Fireflies", 2009, 5, 3, 2, ""),
    # --- the broad wedding canon: all-ages floor fillers ---
    ("Earth, Wind & Fire", "September", 1978, 8, 3, 3, "hype"),
    ("Mark Ronson", "Uptown Funk", 2014, 9, 3, 3, "hype"),
    ("Bruno Mars", "Uptown Funk", 2014, 9, 3, 3, "hype"),
    ("Justin Timberlake", "Can't Stop the Feeling!", 2016, 8, 3, 3, "hype"),
    ("Whitney Houston", "I Wanna Dance with Somebody", 1987, 8, 3, 3, "hype"),
    ("Pharrell Williams", "Happy", 2013, 7, 3, 3, "hype"),
    ("Kool & the Gang", "Celebration", 1980, 8, 3, 3, "hype"),
    ("The Isley Brothers", "Shout", 1959, 8, 3, 3, "hype closer exit-prep"),
    ("OutKast", "Hey Ya!", 2003, 9, 3, 3, "hype"),
    ("Shania Twain", "Man! I Feel Like a Woman!", 1999, 8, 3, 3, "hype"),
    ("Taylor Swift", "Shake It Off", 2014, 8, 3, 3, "hype"),
    ("Walk the Moon", "Shut Up and Dance", 2014, 9, 3, 3, "hype"),
    ("Cyndi Lauper", "Girls Just Want to Have Fun", 1983, 8, 3, 3, ""),
    ("Wham!", "Wake Me Up Before You Go-Go", 1984, 8, 3, 3, ""),
    ("Michael Jackson", "Billie Jean", 1982, 7, 2, 3, ""),
    ("Michael Jackson", "Don't Stop 'Til You Get Enough", 1979, 8, 2, 3, ""),
    ("Bee Gees", "Stayin' Alive", 1977, 7, 2, 3, ""),
    ("Gloria Gaynor", "I Will Survive", 1978, 8, 3, 3, ""),
    ("Sister Sledge", "We Are Family", 1979, 7, 3, 3, ""),
    ("Village People", "Y.M.C.A.", 1978, 8, 3, 3, "line"),
    ("Los Del Rio", "Macarena", 1995, 8, 2, 3, "line"),
    ("Rednex", "Cotton Eye Joe", 1994, 9, 2, 3, "line"),
    ("Billy Ray Cyrus", "Achy Breaky Heart", 1992, 7, 3, 3, "line"),
    ("Tracy Byrd", "Watermelon Crawl", 1994, 7, 2, 2, "line"),
    ("Beyoncé", "Crazy in Love", 2003, 9, 2, 3, ""),
    ("Beyoncé", "Single Ladies (Put a Ring on It)", 2008, 9, 3, 3, ""),
    ("Usher", "Yeah!", 2004, 9, 3, 2, ""),
    ("Dua Lipa", "Levitating", 2020, 8, 2, 2, ""),
    ("Lizzo", "Good as Hell", 2019, 7, 3, 2, ""),
    ("Bruno Mars", "Marry You", 2010, 7, 2, 2, ""),
    ("Van Morrison", "Brown Eyed Girl", 1967, 6, 3, 3, ""),
    ("Wilson Pickett", "Mustang Sally", 1966, 6, 3, 3, ""),
    ("Lynyrd Skynyrd", "Sweet Home Alabama", 1974, 7, 3, 3, "closer"),
    ("Dolly Parton", "9 to 5", 1980, 7, 3, 3, ""),
    ("Garth Brooks", "Friends in Low Places", 1990, 6, 3, 3, "closer"),
    ("Garth Brooks", "Callin' Baton Rouge", 1994, 8, 3, 2, ""),
    ("Florida Georgia Line", "Cruise", 2012, 7, 3, 2, ""),
    ("Luke Combs", "When It Rains It Pours", 2017, 6, 3, 2, ""),
    ("Morgan Wallen", "Whiskey Glasses", 2018, 6, 3, 2, ""),
    ("Tim McGraw", "I Like It, I Love It", 1995, 7, 3, 2, ""),
    ("Toby Keith", "Should've Been a Cowboy", 1993, 6, 3, 2, ""),
    ("Queen", "Don't Stop Me Now", 1979, 9, 3, 3, "closer"),
    ("Neil Diamond", "Sweet Caroline", 1969, 7, 3, 3, "closer exit"),
    ("The Killers", "Mr. Brightside", 2004, 9, 3, 2, "closer exit-prep"),
    ("Semisonic", "Closing Time", 1998, 5, 3, 2, "last-dance"),
    # slow dances and wedding moments
    ("Chris Stapleton", "Tennessee Whiskey", 2015, 3, 3, 3, "slow first-dance"),
    ("Ed Sheeran", "Perfect", 2017, 2, 3, 3, "slow first-dance"),
    ("Ed Sheeran", "Thinking Out Loud", 2014, 3, 3, 3, "slow first-dance"),
    ("John Legend", "All of Me", 2013, 2, 3, 3, "slow first-dance"),
    ("Etta James", "At Last", 1960, 2, 2, 3, "slow first-dance"),
    ("Elvis Presley", "Can't Help Falling in Love", 1961, 2, 3, 3, "slow first-dance last-dance"),
    ("Christina Perri", "A Thousand Years", 2011, 2, 2, 2, "slow first-dance"),
    ("Shania Twain", "From This Moment On", 1998, 2, 2, 2, "slow first-dance"),
    ("Dan + Shay", "Speechless", 2018, 3, 2, 2, "slow first-dance"),
    ("Dan + Shay", "10,000 Hours", 2019, 4, 3, 2, "first-dance"),
    ("Thomas Rhett", "Die a Happy Man", 2015, 3, 3, 2, "slow first-dance"),
    ("Brad Paisley", "Then", 2009, 3, 2, 2, "slow first-dance"),
    ("Rascal Flatts", "Bless the Broken Road", 2004, 3, 3, 2, "slow first-dance"),
    ("Faith Hill", "Breathe", 1999, 3, 3, 2, "slow first-dance"),
    ("Frank Sinatra", "The Way You Look Tonight", 1964, 2, 1, 3, "slow first-dance last-dance"),
    ("Garth Brooks", "The Dance", 1990, 3, 3, 2, "slow last-dance"),
    ("The Temptations", "My Girl", 1964, 5, 3, 3, "father-daughter"),
    ("Louis Armstrong", "What a Wonderful World", 1967, 2, 2, 3, "slow father-daughter"),
    ("Tim McGraw", "My Little Girl", 2006, 3, 1, 2, "slow father-daughter"),
    ("Heartland", "I Loved Her First", 2006, 2, 1, 2, "slow father-daughter"),
    ("Bob Carlisle", "Butterfly Kisses", 1997, 2, 1, 2, "slow father-daughter"),
    ("Rascal Flatts", "My Wish", 2006, 3, 2, 2, "slow father-daughter mother-son"),
    ("Steven Curtis Chapman", "Cinderella", 2007, 2, 1, 1, "slow father-daughter"),
    ("Martina McBride", "In My Daughter's Eyes", 2003, 2, 1, 2, "slow father-daughter"),
    ("Lynyrd Skynyrd", "Simple Man", 1973, 3, 2, 3, "slow mother-son"),
    ("Bette Midler", "Wind Beneath My Wings", 1988, 2, 2, 3, "slow mother-son"),
    ("Lee Ann Womack", "I Hope You Dance", 2000, 3, 2, 2, "slow mother-son"),
)

TAGS = ("hype", "slow", "line", "closer", "first-dance", "father-daughter", "mother-son", "last-dance")


class Known:
    """One song's entry: plain fields, read by set_arranger."""
    __slots__ = ("artist", "title", "year", "energy", "sing", "known", "tags")

    def __init__(self, row: tuple):
        self.artist, self.title, self.year, self.energy, self.sing, self.known, tags = row
        self.tags = frozenset(tags.split())


_INDEX: Optional[tuple] = None


def _index() -> tuple:
    global _INDEX
    if _INDEX is None:
        by_key, by_title = {}, {}
        for row in CANON:
            k = Known(row)
            by_key.setdefault(norm(track_key(k.artist, k.title)), k)
            # a title alone is trusted only when it is two words or more ("Baby" is many songs)
            if len(k.title.split()) >= 2:
                by_title.setdefault(norm(track_key(k.title)), k)
        _INDEX = (by_key, by_title)
    return _INDEX


def lookup(artist: str, title: str) -> Optional[Known]:
    """The table's entry for a song, forgiving "feat.", "(Short Mix)", "(Taylor's Version)" and the
    like; a distinctive title alone is enough (a cover of "Footloose" is still "Footloose")."""
    by_key, by_title = _index()
    for c in candidates(artist or "", title or "", title_only=False):
        hit = by_key.get(norm(c))
        if hit:
            return hit
    for c in candidates("", title or "", title_only=True):
        hit = by_title.get(norm(c))
        if hit:
            return hit
    return None
