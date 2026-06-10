#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Deterministic, byte-stable generator for the eval test-media corpus.

Grows ``tests/fixtures/media/`` from the original hand-curated set to ~200
NFO-described items so the corpus actually discriminates the eval queries in
``backend/tests/fixtures/eval_golden_set.json``.

Design
------
Two item sources, both fully deterministic (sorted iteration, fixed PRNG seed,
no timestamps, no random ordering):

1. **Anchors** — a curated data table (authored from general knowledge) that
   guarantees every ``relevant_titles`` and ``distractors`` title from the
   golden set exists with *accurate real-world metadata*. A "Ridley Scott film"
   query can only resolve if Alien / Blade Runner / The Martian / Gladiator each
   carry ``<director>Ridley Scott</director>``; "Japanese animation" only
   resolves if Spirited Away / Totoro / Mononoke carry ``<country>Japan</country>``.

2. **Synthetic filler** — deterministic volume + dimensional coverage spread
   across genres, decades (pre-2000 → recent), countries, recurring
   directors/actors, and a rating spread. Filler plots are always >= 50 chars.

Output layout (Kodi NFO, matching the existing fixtures):
- Movies:  ``movies/<Title (Year)>/movie.nfo`` + empty ``<Title (Year)> dvd.disc``
- Shows:   ``shows/<Title (Year)>/tvshow.nfo`` + ``Season 01/<Title> S01E01.nfo``
           + empty ``Season 01/<Title> S01E01 dvd.disc`` (episode kept simple,
           following the existing show fixtures as a template)

Every NFO carries a ``<country>`` element using the **full English country
name** (e.g. ``United States of America``, ``Japan``, ``United Kingdom``).
This matches what Jellyfin's NFO parser expects; the backend converts to ISO
3166-1 alpha-2 at sync time via ``app.library.country_codes.name_to_iso``.

Idempotent + byte-stable: running twice produces byte-identical files, so
re-embeds are reproducible. The generator *clears and rewrites* the movies/
and shows/ trees so removed items don't linger.
"""

from __future__ import annotations

import json
import random
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.dom import minidom

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MEDIA_ROOT = _REPO_ROOT / "tests" / "fixtures" / "media"
_GOLDEN_SET = _REPO_ROOT / "backend" / "tests" / "fixtures" / "eval_golden_set.json"

_TARGET_TOTAL = 200
_MIN_PLOT_LENGTH = 50  # must match test_nfo_validation._MIN_PLOT_LENGTH
_SEED = 26  # Spec 26 — fixed seed for byte-stable filler

# Canonical full English country names (Jellyfin NFO convention).
_US = "United States of America"
_GB = "United Kingdom"
_JP = "Japan"
_FR = "France"
_KR = "Korea, Republic of"
_DE = "Germany"
_CA = "Canada"
_AU = "Australia"
_IT = "Italy"
_ES = "Spain"
_SE = "Sweden"
_MX = "Mexico"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Actor:
    """A cast member: display name + role."""

    name: str
    role: str


@dataclass(frozen=True)
class Movie:
    """A movie NFO record."""

    title: str
    year: int
    plot: str
    genres: tuple[str, ...]
    director: str
    actors: tuple[Actor, ...]
    studio: str
    rating: float
    runtime: int
    country: str = _US


@dataclass(frozen=True)
class Show:
    """A tvshow NFO record (single Season 01 / S01E01 episode)."""

    title: str
    year: int
    plot: str
    genres: tuple[str, ...]
    actors: tuple[Actor, ...]
    studio: str
    rating: float
    country: str = _US
    episode_title: str = "Pilot"
    episode_plot: str = ""
    episode_aired: str = ""
    status: str = "Ended"


# --------------------------------------------------------------------------- #
# Anchors — curated, accurate real-world metadata for every golden title
# --------------------------------------------------------------------------- #
def _anchor_movies() -> list[Movie]:
    """Curated movie anchors covering golden relevant_titles + distractors.

    Metadata is authored from general knowledge of these well-known titles:
    directors, years, countries, and dominant genres are real so person/year/
    country eval intents resolve correctly.
    """
    return [
        Movie(
            "Alien",
            1979,
            "The crew of the commercial starship Nostromo encounters a deadly "
            "extraterrestrial creature after investigating a mysterious signal. "
            "Trapped aboard their own ship, they are hunted one by one.",
            ("Sci-Fi", "Horror"),
            "Ridley Scott",
            (
                Actor("Sigourney Weaver", "Ellen Ripley"),
                Actor("Tom Skerritt", "Dallas"),
                Actor("John Hurt", "Kane"),
            ),
            "20th Century Fox",
            8.5,
            117,
            _US,
        ),
        Movie(
            "Blade Runner",
            1982,
            "A burnt-out detective is pulled back into service to hunt down "
            "rogue bioengineered replicants in a rain-soaked future Los Angeles, "
            "questioning what it means to be human.",
            ("Sci-Fi", "Thriller"),
            "Ridley Scott",
            (
                Actor("Harrison Ford", "Rick Deckard"),
                Actor("Rutger Hauer", "Roy Batty"),
                Actor("Sean Young", "Rachael"),
            ),
            "Warner Bros.",
            8.1,
            117,
            _US,
        ),
        Movie(
            "The Martian",
            2015,
            "Stranded alone on Mars after his crew presumes him dead, an "
            "astronaut must use ingenuity and botany to survive while NASA races "
            "to bring him home against impossible odds.",
            ("Sci-Fi", "Adventure", "Drama"),
            "Ridley Scott",
            (
                Actor("Matt Damon", "Mark Watney"),
                Actor("Jessica Chastain", "Melissa Lewis"),
                Actor("Chiwetel Ejiofor", "Vincent Kapoor"),
            ),
            "20th Century Fox",
            8.0,
            144,
            _US,
        ),
        Movie(
            "Gladiator",
            2000,
            "A betrayed Roman general is reduced to slavery and rises through "
            "the gladiatorial arena, seeking vengeance against the corrupt emperor "
            "who murdered his family and stole his command.",
            ("Action", "Drama", "Adventure"),
            "Ridley Scott",
            (
                Actor("Russell Crowe", "Maximus"),
                Actor("Joaquin Phoenix", "Commodus"),
                Actor("Connie Nielsen", "Lucilla"),
            ),
            "DreamWorks Pictures",
            8.5,
            155,
            _US,
        ),
        Movie(
            "Jurassic Park",
            1993,
            "On a remote island, a pioneering theme park populated by cloned "
            "dinosaurs descends into chaos when the security systems fail and the "
            "prehistoric predators break free.",
            ("Sci-Fi", "Adventure", "Thriller"),
            "Steven Spielberg",
            (
                Actor("Sam Neill", "Dr. Alan Grant"),
                Actor("Laura Dern", "Dr. Ellie Sattler"),
                Actor("Jeff Goldblum", "Dr. Ian Malcolm"),
            ),
            "Universal Pictures",
            8.2,
            127,
            _US,
        ),
        Movie(
            "Raiders of the Lost Ark",
            1981,
            "A globe-trotting archaeologist races Nazi agents across deserts and "
            "temples to recover the fabled Ark of the Covenant before its power "
            "can be turned to evil.",
            ("Action", "Adventure"),
            "Steven Spielberg",
            (
                Actor("Harrison Ford", "Indiana Jones"),
                Actor("Karen Allen", "Marion Ravenwood"),
                Actor("Paul Freeman", "Rene Belloq"),
            ),
            "Paramount Pictures",
            8.4,
            115,
            _US,
        ),
        Movie(
            "Jaws",
            1975,
            "When a giant great white shark terrorises a beach resort town, the "
            "local police chief, a marine biologist, and a grizzled fisherman set "
            "out to sea to hunt and destroy it.",
            ("Thriller", "Horror", "Adventure"),
            "Steven Spielberg",
            (
                Actor("Roy Scheider", "Chief Martin Brody"),
                Actor("Robert Shaw", "Quint"),
                Actor("Richard Dreyfuss", "Matt Hooper"),
            ),
            "Universal Pictures",
            8.1,
            124,
            _US,
        ),
        Movie(
            "E.T. the Extra-Terrestrial",
            1982,
            "A lonely suburban boy befriends a gentle alien stranded on Earth and "
            "helps it evade the authorities while building a contraption to phone "
            "home and reunite with its own kind.",
            ("Sci-Fi", "Adventure", "Family"),
            "Steven Spielberg",
            (
                Actor("Henry Thomas", "Elliott"),
                Actor("Drew Barrymore", "Gertie"),
                Actor("Dee Wallace", "Mary"),
            ),
            "Universal Pictures",
            7.9,
            115,
            _US,
        ),
        Movie(
            "Die Hard",
            1988,
            "An off-duty New York cop is caught in a Los Angeles skyscraper when "
            "heavily armed terrorists seize the building, forcing him into a "
            "one-man guerrilla war to save the hostages.",
            ("Action", "Thriller"),
            "John McTiernan",
            (
                Actor("Bruce Willis", "John McClane"),
                Actor("Alan Rickman", "Hans Gruber"),
                Actor("Bonnie Bedelia", "Holly Gennaro"),
            ),
            "20th Century Fox",
            8.2,
            132,
            _US,
        ),
        Movie(
            "Pulp Fiction",
            1994,
            "The lives of two mob hitmen, a boxer, a gangster's wife, and a pair "
            "of diner robbers intertwine in four tales of violence and redemption "
            "told out of chronological order.",
            ("Crime", "Drama", "Thriller"),
            "Quentin Tarantino",
            (
                Actor("John Travolta", "Vincent Vega"),
                Actor("Samuel L. Jackson", "Jules Winnfield"),
                Actor("Bruce Willis", "Butch Coolidge"),
            ),
            "Miramax",
            8.9,
            154,
            _US,
        ),
        Movie(
            "The Sixth Sense",
            1999,
            "A child psychologist tries to help a withdrawn young boy who claims "
            "he can see and speak with the dead, leading both toward a shattering "
            "revelation about themselves.",
            ("Thriller", "Drama", "Horror"),
            "M. Night Shyamalan",
            (
                Actor("Bruce Willis", "Dr. Malcolm Crowe"),
                Actor("Haley Joel Osment", "Cole Sear"),
                Actor("Toni Collette", "Lynn Sear"),
            ),
            "Buena Vista Pictures",
            8.2,
            107,
            _US,
        ),
        Movie(
            "Galaxy Quest",
            1999,
            "The washed-up cast of a cancelled space-opera TV series is abducted "
            "by naive aliens who believe their broadcasts are real, forcing the "
            "actors to become the heroes they only ever played.",
            ("Sci-Fi", "Comedy", "Adventure"),
            "Dean Parisot",
            (
                Actor("Tim Allen", "Jason Nesmith"),
                Actor("Sigourney Weaver", "Gwen DeMarco"),
                Actor("Alan Rickman", "Alexander Dane"),
            ),
            "DreamWorks Pictures",
            7.4,
            102,
            _US,
        ),
        Movie(
            "Mars Attacks!",
            1996,
            "A fleet of mischievous, ray-gun-toting Martians descends on Earth "
            "and gleefully wreaks havoc while bumbling politicians and ordinary "
            "citizens scramble to mount any kind of defence.",
            ("Sci-Fi", "Comedy"),
            "Tim Burton",
            (
                Actor("Jack Nicholson", "President Dale"),
                Actor("Glenn Close", "First Lady"),
                Actor("Pierce Brosnan", "Donald Kessler"),
            ),
            "Warner Bros.",
            6.4,
            106,
            _US,
        ),
        Movie(
            "Shaun of the Dead",
            2004,
            "A directionless London salesman tries to win back his girlfriend and "
            "reconcile with his mother while a zombie apocalypse erupts around "
            "them, retreating to the only safe place he knows: the pub.",
            ("Comedy", "Horror"),
            "Edgar Wright",
            (
                Actor("Simon Pegg", "Shaun"),
                Actor("Nick Frost", "Ed"),
                Actor("Kate Ashfield", "Liz"),
            ),
            "Universal Pictures",
            7.9,
            99,
            _GB,
        ),
        Movie(
            "The Shining",
            1980,
            "A struggling writer takes a winter caretaker job at an isolated "
            "mountain hotel where supernatural forces and crushing isolation drive "
            "him toward madness and violence against his family.",
            ("Horror", "Drama", "Thriller"),
            "Stanley Kubrick",
            (
                Actor("Jack Nicholson", "Jack Torrance"),
                Actor("Shelley Duvall", "Wendy Torrance"),
                Actor("Danny Lloyd", "Danny Torrance"),
            ),
            "Warner Bros.",
            8.4,
            146,
            _US,
        ),
        Movie(
            "Get Out",
            2017,
            "A young Black man visits his white girlfriend's family estate for the "
            "weekend and slowly uncovers a horrifying secret beneath their "
            "unnervingly polite hospitality.",
            ("Horror", "Thriller", "Mystery"),
            "Jordan Peele",
            (
                Actor("Daniel Kaluuya", "Chris Washington"),
                Actor("Allison Williams", "Rose Armitage"),
                Actor("Bradley Whitford", "Dean Armitage"),
            ),
            "Universal Pictures",
            7.7,
            104,
            _US,
        ),
        Movie(
            "A Quiet Place",
            2018,
            "In a world overrun by blind creatures that hunt by sound, a family "
            "survives by living in absolute silence, every footstep and breath a "
            "potentially fatal risk to their children.",
            ("Horror", "Thriller", "Drama"),
            "John Krasinski",
            (
                Actor("Emily Blunt", "Evelyn Abbott"),
                Actor("John Krasinski", "Lee Abbott"),
                Actor("Millicent Simmonds", "Regan Abbott"),
            ),
            "Paramount Pictures",
            7.5,
            90,
            _US,
        ),
        Movie(
            "Se7en",
            1995,
            "Two homicide detectives hunt a meticulous serial killer who stages "
            "his murders as gruesome tableaux of the seven deadly sins, leading "
            "them toward a devastating final confrontation.",
            ("Crime", "Thriller", "Mystery"),
            "David Fincher",
            (
                Actor("Brad Pitt", "Detective Mills"),
                Actor("Morgan Freeman", "Detective Somerset"),
                Actor("Gwyneth Paltrow", "Tracy Mills"),
            ),
            "New Line Cinema",
            8.6,
            127,
            _US,
        ),
        Movie(
            "Zodiac",
            2007,
            "A cartoonist, a crime reporter, and detectives become obsessed over "
            "decades with identifying the cryptic Zodiac killer terrorising the "
            "San Francisco Bay Area through taunting letters and ciphers.",
            ("Crime", "Thriller", "Mystery"),
            "David Fincher",
            (
                Actor("Jake Gyllenhaal", "Robert Graysmith"),
                Actor("Mark Ruffalo", "Inspector Toschi"),
                Actor("Robert Downey Jr.", "Paul Avery"),
            ),
            "Paramount Pictures",
            7.7,
            157,
            _US,
        ),
        Movie(
            "Sicario",
            2015,
            "An idealistic FBI agent is recruited into a shadowy task force "
            "operating along the US-Mexico border, where the rules of engagement "
            "dissolve into moral ambiguity and brutal cartel warfare.",
            ("Crime", "Thriller", "Action"),
            "Denis Villeneuve",
            (
                Actor("Emily Blunt", "Kate Macer"),
                Actor("Benicio del Toro", "Alejandro"),
                Actor("Josh Brolin", "Matt Graver"),
            ),
            "Lionsgate",
            7.6,
            121,
            _US,
        ),
        Movie(
            "The Goonies",
            1985,
            "A band of small-town kids facing the loss of their homes follows an "
            "old pirate treasure map into a network of caves, pursued by a family "
            "of crooks and booby traps along the way.",
            ("Adventure", "Comedy", "Family"),
            "Richard Donner",
            (
                Actor("Sean Astin", "Mikey"),
                Actor("Josh Brolin", "Brand"),
                Actor("Corey Feldman", "Mouth"),
            ),
            "Warner Bros.",
            7.7,
            114,
            _US,
        ),
        Movie(
            "Ghostbusters",
            1984,
            "Three eccentric parapsychologists start a ghost-catching business in "
            "New York City just as a surge of supernatural activity threatens to "
            "unleash an ancient destructive deity on Manhattan.",
            ("Comedy", "Sci-Fi", "Fantasy"),
            "Ivan Reitman",
            (
                Actor("Bill Murray", "Dr. Peter Venkman"),
                Actor("Dan Aykroyd", "Dr. Raymond Stantz"),
                Actor("Sigourney Weaver", "Dana Barrett"),
            ),
            "Columbia Pictures",
            7.8,
            105,
            _US,
        ),
        Movie(
            "The Matrix",
            1999,
            "A disillusioned hacker discovers that reality is a simulated prison "
            "built by machines and joins a band of rebels fighting to free "
            "humanity from the digital dream world.",
            ("Sci-Fi", "Action"),
            "The Wachowskis",
            (
                Actor("Keanu Reeves", "Neo"),
                Actor("Laurence Fishburne", "Morpheus"),
                Actor("Carrie-Anne Moss", "Trinity"),
            ),
            "Warner Bros.",
            8.7,
            136,
            _US,
        ),
        Movie(
            "The Shawshank Redemption",
            1994,
            "Wrongly convicted of murder, a quiet banker forms an enduring "
            "friendship inside a brutal prison and clings to hope across two "
            "decades while quietly engineering his own redemption.",
            ("Drama", "Crime"),
            "Frank Darabont",
            (
                Actor("Tim Robbins", "Andy Dufresne"),
                Actor("Morgan Freeman", "Ellis Boyd Redding"),
                Actor("Bob Gunton", "Warden Norton"),
            ),
            "Columbia Pictures",
            9.3,
            142,
            _US,
        ),
        Movie(
            "Interstellar",
            2014,
            "As a dying Earth runs out of food, a former pilot leads a desperate "
            "mission through a wormhole in search of a new home for humanity, "
            "wrestling with relativity, sacrifice, and love across the stars.",
            ("Sci-Fi", "Adventure", "Drama"),
            "Christopher Nolan",
            (
                Actor("Matthew McConaughey", "Cooper"),
                Actor("Anne Hathaway", "Brand"),
                Actor("Jessica Chastain", "Murph"),
            ),
            "Paramount Pictures",
            8.6,
            169,
            _US,
        ),
        Movie(
            "Arrival",
            2016,
            "When mysterious alien craft touch down across the globe, a "
            "linguist is recruited to decipher their language and discovers that "
            "understanding it reshapes her perception of time itself.",
            ("Sci-Fi", "Drama", "Mystery"),
            "Denis Villeneuve",
            (
                Actor("Amy Adams", "Louise Banks"),
                Actor("Jeremy Renner", "Ian Donnelly"),
                Actor("Forest Whitaker", "Colonel Weber"),
            ),
            "Paramount Pictures",
            7.9,
            116,
            _US,
        ),
        Movie(
            "Mad Max Fury Road",
            2015,
            "On a post-apocalyptic desert highway, a haunted drifter and a "
            "rebel warrior flee a tyrannical warlord in a relentless, "
            "vehicular chase to deliver his captive brides to freedom.",
            ("Action", "Adventure", "Sci-Fi"),
            "George Miller",
            (
                Actor("Tom Hardy", "Max Rockatansky"),
                Actor("Charlize Theron", "Imperator Furiosa"),
                Actor("Nicholas Hoult", "Nux"),
            ),
            "Warner Bros.",
            8.1,
            120,
            _AU,
        ),
        Movie(
            "Good Will Hunting",
            1997,
            "A defiant young janitor with a genius for mathematics is drawn out "
            "of his self-destructive habits by a grieving therapist who helps him "
            "confront his past and embrace his potential.",
            ("Drama",),
            "Gus Van Sant",
            (
                Actor("Matt Damon", "Will Hunting"),
                Actor("Robin Williams", "Sean Maguire"),
                Actor("Ben Affleck", "Chuckie Sullivan"),
            ),
            "Miramax",
            8.3,
            126,
            _US,
        ),
        Movie(
            "Moonlight",
            2016,
            "Told in three tender chapters, a young Black man growing up in Miami "
            "struggles with identity, sexuality, and belonging while searching for "
            "connection amid hardship and self-discovery.",
            ("Drama",),
            "Barry Jenkins",
            (
                Actor("Trevante Rhodes", "Chiron"),
                Actor("Mahershala Ali", "Juan"),
                Actor("Naomie Harris", "Paula"),
            ),
            "A24",
            7.4,
            111,
            _US,
        ),
        Movie(
            "Spirited Away",
            2001,
            "A sullen ten-year-old girl wanders into a spirit world where her "
            "parents are transformed into pigs, and must work in a bathhouse for "
            "the gods to find the courage to free them and herself.",
            ("Animation", "Fantasy", "Adventure"),
            "Hayao Miyazaki",
            (
                Actor("Rumi Hiiragi", "Chihiro (voice)"),
                Actor("Miyu Irino", "Haku (voice)"),
                Actor("Mari Natsuki", "Yubaba (voice)"),
            ),
            "Studio Ghibli",
            8.6,
            125,
            _JP,
        ),
        Movie(
            "My Neighbor Totoro",
            1988,
            "Two young sisters who move to the countryside to be near their "
            "hospitalised mother befriend gentle forest spirits, including a "
            "giant, furry guardian of the woods named Totoro.",
            ("Animation", "Fantasy", "Family"),
            "Hayao Miyazaki",
            (
                Actor("Noriko Hidaka", "Satsuki (voice)"),
                Actor("Chika Sakamoto", "Mei (voice)"),
                Actor("Shigesato Itoi", "Tatsuo (voice)"),
            ),
            "Studio Ghibli",
            8.1,
            86,
            _JP,
        ),
        Movie(
            "Princess Mononoke",
            1997,
            "A young prince cursed by a dying boar god travels west and is caught "
            "between the encroaching iron-working humans and the ancient forest "
            "spirits and the wolf-raised girl who defends them.",
            ("Animation", "Fantasy", "Adventure"),
            "Hayao Miyazaki",
            (
                Actor("Yoji Matsuda", "Ashitaka (voice)"),
                Actor("Yuriko Ishida", "San (voice)"),
                Actor("Yuko Tanaka", "Lady Eboshi (voice)"),
            ),
            "Studio Ghibli",
            8.4,
            134,
            _JP,
        ),
        Movie(
            "Shrek",
            2001,
            "A grumpy green ogre reluctantly teams up with a motormouthed donkey "
            "to rescue a feisty princess and reclaim his swamp, discovering "
            "friendship and love along the way.",
            ("Animation", "Comedy", "Adventure"),
            "Andrew Adamson",
            (
                Actor("Mike Myers", "Shrek (voice)"),
                Actor("Eddie Murphy", "Donkey (voice)"),
                Actor("Cameron Diaz", "Princess Fiona (voice)"),
            ),
            "DreamWorks Animation",
            7.9,
            90,
            _US,
        ),
        Movie(
            "Parasite",
            2019,
            "A destitute family schemes its way into the household of a wealthy "
            "clan by posing as unrelated, qualified workers, until a buried secret "
            "erupts into shocking class violence.",
            ("Drama", "Thriller", "Comedy"),
            "Bong Joon-ho",
            (
                Actor("Song Kang-ho", "Kim Ki-taek"),
                Actor("Lee Sun-kyun", "Park Dong-ik"),
                Actor("Cho Yeo-jeong", "Choi Yeon-gyo"),
            ),
            "CJ Entertainment",
            8.5,
            132,
            _KR,
        ),
        Movie(
            "Amelie",
            2001,
            "A whimsical, shy Parisian waitress secretly orchestrates small acts "
            "of kindness and mischief in the lives of those around her, all while "
            "summoning the courage to pursue her own happiness.",
            ("Comedy", "Romance", "Drama"),
            "Jean-Pierre Jeunet",
            (
                Actor("Audrey Tautou", "Amelie Poulain"),
                Actor("Mathieu Kassovitz", "Nino Quincampoix"),
                Actor("Rufus", "Raphael Poulain"),
            ),
            "UGC-Fox Distribution",
            8.3,
            122,
            _FR,
        ),
        Movie(
            "Knives Out",
            2019,
            "When a wealthy crime novelist is found dead after his birthday party, "
            "a flamboyant private detective sifts through a household of "
            "self-serving relatives to untangle a web of lies and inheritance.",
            ("Mystery", "Crime", "Comedy"),
            "Rian Johnson",
            (
                Actor("Daniel Craig", "Benoit Blanc"),
                Actor("Ana de Armas", "Marta Cabrera"),
                Actor("Chris Evans", "Ransom Drysdale"),
            ),
            "Lionsgate",
            7.9,
            130,
            _US,
        ),
    ]


def _anchor_shows() -> list[Show]:
    """Curated show anchors covering golden TV relevant_titles + distractors."""
    return [
        Show(
            "Babylon 5",
            1993,
            "A five-mile-long space station serves as a diplomatic hub for alien "
            "civilizations and humans in the 23rd century, as ancient forces "
            "awaken and political intrigue escalates toward galactic war.",
            ("Sci-Fi", "Space Opera", "Drama"),
            (
                Actor("Bruce Boxleitner", "Captain John Sheridan"),
                Actor("Claudia Christian", "Commander Susan Ivanova"),
            ),
            "PTEN",
            8.3,
            _US,
            "Midnight on the Firing Line",
            "Raiders threaten station supply lines as the Narn and Centauri edge "
            "toward open conflict, and a new telepath arrives aboard the station.",
            "1994-01-26",
        ),
        Show(
            "Stargate SG-1",
            1997,
            "A covert military team travels through an ancient ring-shaped portal "
            "to distant worlds, defending Earth from parasitic alien overlords "
            "and uncovering the galaxy's buried history.",
            ("Sci-Fi", "Adventure", "Space Opera"),
            (
                Actor("Richard Dean Anderson", "Jack O'Neill"),
                Actor("Amanda Tapping", "Samantha Carter"),
            ),
            "Showtime",
            8.4,
            _US,
            "Children of the Gods",
            "A reactivated gate program assembles a new team after an alien "
            "incursion, sending them on their first mission off-world.",
            "1997-07-27",
        ),
        Show(
            "Battlestar Galactica",
            2004,
            "After robotic Cylons annihilate the human colonies, a ragtag fleet "
            "led by an aging warship flees through space in search of a fabled "
            "refuge called Earth, hunted at every jump.",
            ("Sci-Fi", "Space Opera", "Drama"),
            (
                Actor("Edward James Olmos", "Admiral William Adama"),
                Actor("Mary McDonnell", "President Laura Roslin"),
            ),
            "Sci-Fi Channel",
            8.7,
            _US,
            "33",
            "Pursued relentlessly by the Cylons every thirty-three minutes, the "
            "exhausted fleet must keep jumping to survive.",
            "2004-10-18",
        ),
        Show(
            "Firefly",
            2002,
            "The renegade crew of a worn-out transport ship takes any job, legal "
            "or not, to stay flying on the ragged frontier of a war-scarred "
            "interstellar system while dodging the oppressive Alliance.",
            ("Sci-Fi", "Space Opera", "Western"),
            (
                Actor("Nathan Fillion", "Malcolm Reynolds"),
                Actor("Gina Torres", "Zoe Washburne"),
            ),
            "20th Century Fox Television",
            9.0,
            _US,
            "Serenity",
            "The crew takes on two new passengers and a risky salvage job that "
            "draws the attention of both the Alliance and dangerous outlaws.",
            "2002-12-20",
        ),
        Show(
            "Midsomer Murders",
            1997,
            "A patient Detective Chief Inspector investigates an improbable "
            "string of murders in the deceptively idyllic villages of an English "
            "county, where every quaint resident hides a motive.",
            ("Crime", "Mystery", "Drama"),
            (
                Actor("John Nettles", "DCI Tom Barnaby"),
                Actor("Daniel Casey", "DS Gavin Troy"),
            ),
            "ITV",
            7.5,
            _GB,
            "The Killings at Badger's Drift",
            "When an elderly woman dies after witnessing something she shouldn't "
            "have, Barnaby uncovers dark secrets beneath a tranquil village.",
            "1997-03-23",
        ),
        Show(
            "Death in Paradise",
            2011,
            "A buttoned-up British detective is reassigned to a sun-drenched "
            "Caribbean island, solving improbable locked-room murders while "
            "battling the heat, the wildlife, and his own discomfort.",
            ("Crime", "Mystery", "Comedy"),
            (
                Actor("Ben Miller", "DI Richard Poole"),
                Actor("Sara Martins", "DS Camille Bordey"),
            ),
            "BBC",
            7.5,
            _GB,
            "Arriving in Paradise",
            "A detective flown in to investigate a colleague's murder finds "
            "himself stranded on the island as the new lead investigator.",
            "2011-10-25",
        ),
        Show(
            "Broadchurch",
            2013,
            "The murder of a young boy shatters a close-knit English seaside town "
            "as two mismatched detectives investigate, exposing the secrets and "
            "fractures hidden beneath the community's grief.",
            ("Crime", "Drama", "Mystery"),
            (
                Actor("David Tennant", "DI Alec Hardy"),
                Actor("Olivia Colman", "DS Ellie Miller"),
            ),
            "ITV",
            8.4,
            _GB,
            "Episode One",
            "A boy's body is found on the beach, and the town's tight bonds begin "
            "to strain as suspicion spreads and the investigation begins.",
            "2013-03-04",
        ),
        Show(
            "Breaking Bad",
            2008,
            "A mild-mannered high school chemistry teacher diagnosed with cancer "
            "turns to manufacturing methamphetamine to secure his family's future, "
            "descending step by step into a ruthless criminal empire.",
            ("Crime", "Drama", "Thriller"),
            (
                Actor("Bryan Cranston", "Walter White"),
                Actor("Aaron Paul", "Jesse Pinkman"),
            ),
            "AMC",
            9.5,
            _US,
            "Pilot",
            "A diagnosis pushes a struggling teacher to partner with a former "
            "student and cook his first batch, with disastrous complications.",
            "2008-01-20",
        ),
        Show(
            "The Wire",
            2002,
            "Across a sprawling portrait of Baltimore, detectives, dealers, "
            "dockworkers, politicians, and teachers reveal how broken "
            "institutions grind down everyone caught inside them.",
            ("Crime", "Drama", "Thriller"),
            (
                Actor("Dominic West", "Jimmy McNulty"),
                Actor("Idris Elba", "Stringer Bell"),
            ),
            "HBO",
            9.3,
            _US,
            "The Target",
            "A frustrated detective sets in motion a wiretap investigation into a "
            "violent and elusive West Baltimore drug organisation.",
            "2002-06-02",
        ),
        Show(
            "The X-Files",
            1993,
            "Two FBI agents, one a believer and one a skeptic, investigate "
            "unsolved cases involving the paranormal, alien conspiracies, and "
            "government cover-ups that reach to the highest levels.",
            ("Sci-Fi", "Mystery", "Drama"),
            (
                Actor("David Duchovny", "Fox Mulder"),
                Actor("Gillian Anderson", "Dana Scully"),
            ),
            "20th Century Fox Television",
            8.6,
            _US,
            "Pilot",
            "A skeptical agent is assigned to debunk a believer's work, only to "
            "confront unexplained deaths in a small Oregon town.",
            "1993-09-10",
        ),
        Show(
            "Fringe",
            2008,
            "A special FBI division investigates a wave of unexplained, often "
            "grotesque phenomena tied to fringe science and a parallel universe "
            "encroaching on our own.",
            ("Sci-Fi", "Mystery", "Drama"),
            (
                Actor("Anna Torv", "Olivia Dunham"),
                Actor("Joshua Jackson", "Peter Bishop"),
            ),
            "Warner Bros. Television",
            8.0,
            _US,
            "Pilot",
            "An agent recruits an institutionalised scientist and his son to "
            "investigate a deadly outbreak with no rational explanation.",
            "2008-09-09",
        ),
    ]


# --------------------------------------------------------------------------- #
# Synthetic filler — deterministic dimensional coverage to ~200 items
# --------------------------------------------------------------------------- #
# Recurring directors / actors so person-style coverage has volume.
_FILLER_DIRECTORS = (
    "Ava Marchetti",
    "Daniel Okonkwo",
    "Elena Vasquez",
    "Hiroshi Tanaka",
    "Klaus Bergmann",
    "Liam O'Sullivan",
    "Margot Lefevre",
    "Nadia Petrova",
    "Olivia Chen",
    "Rafael Santos",
)
_FILLER_ACTORS = (
    "Aria Lindqvist",
    "Caleb Mercer",
    "Diego Morales",
    "Freya Nilsson",
    "Grace Abara",
    "Henry Whitfield",
    "Ines Dubois",
    "Kenji Sato",
    "Lucia Romano",
    "Marcus Reed",
    "Nina Kowalski",
    "Omar Haddad",
    "Priya Nair",
    "Sofia Castellano",
    "Theo Andersson",
    "Yara Cohen",
)
# (country, studio) pairs — distribution skewed toward US/GB but broad.
_FILLER_LOCALES = (
    (_US, "Beacon Hill Pictures"),
    (_US, "Cascade Studios"),
    (_GB, "Albion Film Company"),
    (_FR, "Lumiere Productions"),
    (_JP, "Sakura Eiga"),
    (_KR, "Hangang Studios"),
    (_DE, "Rheinland Films"),
    (_CA, "Maple Frame Pictures"),
    (_IT, "Cinema Aurora"),
    (_ES, "Estudios Mediterraneo"),
    (_SE, "Norrsken Film"),
    (_MX, "Cine Azteca"),
)
# Genre clusters with plot scaffolding tuned to read as the genre.
_FILLER_GENRES = (
    ("Drama", "a quiet, character-driven story of"),
    ("Comedy", "a warm, offbeat comedy about"),
    ("Thriller", "a tightly wound thriller following"),
    ("Sci-Fi", "a speculative science-fiction tale of"),
    ("Horror", "a slow-burning horror story about"),
    ("Romance", "a bittersweet romance between"),
    ("Adventure", "a sweeping adventure across"),
    ("Mystery", "a twisting mystery surrounding"),
    ("Crime", "a gritty crime saga tracing"),
    ("Fantasy", "a richly imagined fantasy where"),
    ("Action", "a high-octane action story pitting"),
    ("Documentary", "an intimate documentary portrait of"),
)
_FILLER_SUBJECTS = (
    "a small mountain town and the secret it has kept for generations",
    "two estranged siblings forced to share a crumbling family estate",
    "a night-shift worker who stumbles onto something they cannot unsee",
    "a touring musician chasing one last shot at redemption",
    "a coastal community bracing for a storm that never quite arrives",
    "a retired detective drawn back for one final, personal case",
    "a generation ship whose crew has forgotten where they came from",
    "a translator caught between two worlds and two loyalties",
    "a young apprentice who discovers their mentor's hidden past",
    "a stranded traveller relying on the kindness of unlikely allies",
    "a town of misfits banding together against a faceless authority",
    "a lighthouse keeper haunted by a voice in the fog",
)
_FILLER_TITLE_NOUNS = (
    "Harbor",
    "Echo",
    "Lantern",
    "Cinder",
    "Meridian",
    "Hollow",
    "Tideline",
    "Vesper",
    "Threshold",
    "Glasshouse",
    "Northwind",
    "Saffron",
    "Ironwood",
    "Halcyon",
    "Driftwood",
    "Solstice",
)
_FILLER_TITLE_ADJS = (
    "Last",
    "Silent",
    "Distant",
    "Broken",
    "Golden",
    "Crimson",
    "Quiet",
    "Hidden",
    "Endless",
    "Pale",
    "Wandering",
    "Forgotten",
)


@dataclass
class _FillerState:
    """Mutable cursor for deterministic uniqueness tracking."""

    rng: random.Random
    used_keys: set[tuple[str, int]] = field(default_factory=set)


def _make_filler_movie(index: int, state: _FillerState) -> Movie:
    """Build one deterministic synthetic movie from the index + seeded RNG."""
    genre_name, lead_in = _FILLER_GENRES[index % len(_FILLER_GENRES)]
    secondary = _FILLER_GENRES[(index + 4) % len(_FILLER_GENRES)][0]
    adj = _FILLER_TITLE_ADJS[index % len(_FILLER_TITLE_ADJS)]
    noun_idx = (index // len(_FILLER_TITLE_ADJS)) % len(_FILLER_TITLE_NOUNS)
    noun = _FILLER_TITLE_NOUNS[noun_idx]
    title = f"The {adj} {noun}"
    # Year spread: 1972 -> 2023, deterministic stride.
    year = 1972 + (index * 7) % 52
    country, studio = _FILLER_LOCALES[index % len(_FILLER_LOCALES)]
    director = _FILLER_DIRECTORS[index % len(_FILLER_DIRECTORS)]
    a1 = _FILLER_ACTORS[index % len(_FILLER_ACTORS)]
    a2 = _FILLER_ACTORS[(index + 5) % len(_FILLER_ACTORS)]
    a3 = _FILLER_ACTORS[(index + 9) % len(_FILLER_ACTORS)]
    subject = _FILLER_SUBJECTS[index % len(_FILLER_SUBJECTS)]
    plot = (
        f"In this {genre_name.lower()} feature, {lead_in} {subject}. "
        f"As events unfold, loyalties are tested and nothing stays as it seems."
    )
    # Rating spread 5.0 -> 8.4 deterministic.
    rating = round(5.0 + ((index * 13) % 35) / 10.0, 1)
    runtime = 84 + (index * 11) % 80
    # Ensure unique (title, year): nudge year forward on collision.
    while (title, year) in state.used_keys:
        year += 1
    state.used_keys.add((title, year))
    genres = (genre_name, secondary) if secondary != genre_name else (genre_name,)
    return Movie(
        title=title,
        year=year,
        plot=plot,
        genres=genres,
        director=director,
        actors=(
            Actor(a1, "Lead"),
            Actor(a2, "Supporting"),
            Actor(a3, "Featured"),
        ),
        studio=studio,
        rating=rating,
        runtime=runtime,
        country=country,
    )


def _make_filler_show(index: int, state: _FillerState) -> Show:
    """Build one deterministic synthetic show."""
    genre_name, lead_in = _FILLER_GENRES[index % len(_FILLER_GENRES)]
    adj = _FILLER_TITLE_ADJS[(index + 3) % len(_FILLER_TITLE_ADJS)]
    noun = _FILLER_TITLE_NOUNS[(index + 2) % len(_FILLER_TITLE_NOUNS)]
    title = f"{adj} {noun} Chronicles"
    year = 1990 + (index * 5) % 33
    country, studio = _FILLER_LOCALES[(index + 1) % len(_FILLER_LOCALES)]
    a1 = _FILLER_ACTORS[(index + 2) % len(_FILLER_ACTORS)]
    a2 = _FILLER_ACTORS[(index + 7) % len(_FILLER_ACTORS)]
    subject = _FILLER_SUBJECTS[(index + 6) % len(_FILLER_SUBJECTS)]
    plot = (
        f"An episodic {genre_name.lower()} series, {lead_in} {subject}. "
        f"Each season deepens the mystery while the ensemble cast evolves."
    )
    rating = round(5.5 + ((index * 17) % 30) / 10.0, 1)
    while (title, year) in state.used_keys:
        year += 1
    state.used_keys.add((title, year))
    genres = (genre_name, "Drama") if genre_name != "Drama" else ("Drama",)
    return Show(
        title=title,
        year=year,
        plot=plot,
        genres=genres,
        actors=(Actor(a1, "Lead"), Actor(a2, "Co-Lead")),
        studio=studio,
        rating=rating,
        country=country,
        episode_title="Pilot",
        episode_plot=(
            f"The opening chapter introduces {subject}, setting the tone for the "
            f"series and planting the questions the season will pursue."
        ),
        episode_aired=f"{year}-09-15",
    )


# --------------------------------------------------------------------------- #
# NFO serialisation — byte-stable, indented to match existing fixtures
# --------------------------------------------------------------------------- #
def _indent_xml(root: ET.Element) -> str:
    """Serialise with two-space indentation and a stable XML declaration."""
    rough = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    # Drop the blank lines minidom inserts and normalise the declaration to the
    # fixture-standard one.
    lines = [ln for ln in pretty.split("\n") if ln.strip()]
    lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    return "\n".join(lines) + "\n"


def _movie_to_xml(movie: Movie) -> str:
    root = ET.Element("movie")
    ET.SubElement(root, "title").text = movie.title
    ET.SubElement(root, "year").text = str(movie.year)
    ET.SubElement(root, "plot").text = movie.plot
    for genre in movie.genres:
        ET.SubElement(root, "genre").text = genre
    ET.SubElement(root, "director").text = movie.director
    for actor in movie.actors:
        actor_el = ET.SubElement(root, "actor")
        ET.SubElement(actor_el, "name").text = actor.name
        ET.SubElement(actor_el, "role").text = actor.role
    ET.SubElement(root, "studio").text = movie.studio
    ET.SubElement(root, "rating").text = f"{movie.rating:.1f}"
    ET.SubElement(root, "runtime").text = str(movie.runtime)
    ET.SubElement(root, "country").text = movie.country
    return _indent_xml(root)


def _show_to_xml(show: Show) -> str:
    root = ET.Element("tvshow")
    ET.SubElement(root, "title").text = show.title
    ET.SubElement(root, "year").text = str(show.year)
    ET.SubElement(root, "plot").text = show.plot
    for genre in show.genres:
        ET.SubElement(root, "genre").text = genre
    for actor in show.actors:
        actor_el = ET.SubElement(root, "actor")
        ET.SubElement(actor_el, "name").text = actor.name
        ET.SubElement(actor_el, "role").text = actor.role
    ET.SubElement(root, "studio").text = show.studio
    ET.SubElement(root, "rating").text = f"{show.rating:.1f}"
    ET.SubElement(root, "status").text = show.status
    ET.SubElement(root, "country").text = show.country
    return _indent_xml(root)


def _episode_to_xml(show: Show) -> str:
    root = ET.Element("episodedetails")
    ET.SubElement(root, "title").text = show.episode_title
    ET.SubElement(root, "season").text = "1"
    ET.SubElement(root, "episode").text = "1"
    plot = show.episode_plot or show.plot
    ET.SubElement(root, "plot").text = plot
    if show.episode_aired:
        ET.SubElement(root, "aired").text = show.episode_aired
    return _indent_xml(root)


# --------------------------------------------------------------------------- #
# Filesystem emission
# --------------------------------------------------------------------------- #
def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _emit_movie(movie: Movie) -> None:
    dir_name = f"{movie.title} ({movie.year})"
    movie_dir = _MEDIA_ROOT / "movies" / dir_name
    _write_text(movie_dir / "movie.nfo", _movie_to_xml(movie))
    # Empty .disc stub (byte-stable: zero bytes).
    _write_text(movie_dir / f"{dir_name} dvd.disc", "")


def _emit_show(show: Show) -> None:
    dir_name = f"{show.title} ({show.year})"
    show_dir = _MEDIA_ROOT / "shows" / dir_name
    _write_text(show_dir / "tvshow.nfo", _show_to_xml(show))
    season_dir = show_dir / "Season 01"
    ep_base = f"{show.title} S01E01"
    _write_text(season_dir / f"{ep_base}.nfo", _episode_to_xml(show))
    _write_text(season_dir / f"{ep_base} dvd.disc", "")


def _load_golden_titles() -> set[str]:
    """Every relevant_titles + distractors title that MUST exist as an anchor."""
    data = json.loads(_GOLDEN_SET.read_text(encoding="utf-8"))
    titles: set[str] = set()
    for case in data:
        titles.update(case.get("relevant_titles", []))
        titles.update(case.get("distractors", []))
    return titles


def _verify_golden_coverage(movies: list[Movie], shows: list[Show]) -> None:
    """Fail fast if any golden title lacks an anchor with accurate metadata."""
    present = {m.title for m in movies} | {s.title for s in shows}
    required = _load_golden_titles()
    missing = sorted(required - present)
    if missing:
        msg = (
            "Golden-set titles missing from anchor corpus (add accurate "
            f"anchors before generating): {missing}"
        )
        raise SystemExit(msg)


def build_corpus() -> tuple[list[Movie], list[Show]]:
    """Assemble the full deterministic corpus: anchors + filler to ~200."""
    movies = _anchor_movies()
    shows = _anchor_shows()
    _verify_golden_coverage(movies, shows)

    # Keep shows to ~15-20; bulk is movies. Target ~200 total.
    target_shows = 18
    state = _FillerState(rng=random.Random(_SEED))
    state.used_keys = {(s.title, s.year) for s in shows}
    show_index = 0
    while len(shows) < target_shows:
        shows.append(_make_filler_show(show_index, state))
        show_index += 1

    movie_target = _TARGET_TOTAL - len(shows)
    state.used_keys = {(m.title, m.year) for m in movies}
    movie_index = 0
    while len(movies) < movie_target:
        movies.append(_make_filler_movie(movie_index, state))
        movie_index += 1

    # Deterministic output order.
    movies.sort(key=lambda m: (m.title, m.year))
    shows.sort(key=lambda s: (s.title, s.year))
    return movies, shows


def main() -> None:
    """Regenerate the entire movies/ and shows/ corpus deterministically."""
    movies, shows = build_corpus()

    # Clear-and-rewrite so removed items don't linger (idempotent).
    for sub in ("movies", "shows"):
        target = _MEDIA_ROOT / sub
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    for movie in movies:
        _emit_movie(movie)
    for show in shows:
        _emit_show(show)

    nfo_count = len(movies) + len(shows) * 2
    print(
        f"Generated corpus: {len(movies)} movies + {len(shows)} shows "
        f"= {len(movies) + len(shows)} items ({nfo_count} NFO files)."
    )


if __name__ == "__main__":
    main()
