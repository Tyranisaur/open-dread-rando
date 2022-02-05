import copy
import functools
import json
from enum import Enum
from pathlib import Path

from mercury_engine_data_structures.formats import Bmsad, Txt

from open_dread_rando import lua_util
from open_dread_rando.model_data import ALL_MODEL_DATA
from open_dread_rando.patcher_editor import PatcherEditor, path_for_level


@functools.cache
def _read_template_powerup():
    with Path(__file__).parent.joinpath("templates", "template_powerup_bmsad.json").open() as f:
        return json.load(f)


def _read_powerup_lua() -> bytes:
    return Path(__file__).parent.joinpath("files", "randomizer_powerup.lua").read_bytes()


class PickupType(Enum):
    ACTOR = "actor"
    EMMI = "emmi"
    COREX = "corex"
    CORPIUS = "corpius"

    def patch_pickup(self, editor: PatcherEditor, pickup: dict, pickup_id: int):
        if self == PickupType.ACTOR:
            patch_actor_pickup(editor, pickup, pickup_id)
        if self == PickupType.EMMI:
            patch_emmi_pickup(editor, pickup, pickup_id)
        if self == PickupType.COREX:
            patch_corex_pickup(editor, pickup, pickup_id)
        if self == PickupType.CORPIUS:
            patch_corpius_pickup(editor, pickup, pickup_id)


def patch_actor_pickup(editor: PatcherEditor, pickup: dict, pickup_id: int):
    template_bmsad = _read_template_powerup()

    pkgs_for_level = set(editor.find_pkgs(path_for_level(pickup["pickup_actor"]["scenario"]) + ".brfld"))

    level = editor.get_scenario(pickup["pickup_actor"]["scenario"])
    actor = level.actors_for_layer(pickup["pickup_actor"]["layer"])[pickup["pickup_actor"]["actor"]]

    model_name: str = pickup["model"]
    model_data = ALL_MODEL_DATA.get(model_name, ALL_MODEL_DATA["itemsphere"])

    new_template = copy.deepcopy(template_bmsad)
    new_template["name"] = f"randomizer_powerup_{pickup_id}"

    # Update used model
    new_template["property"]["model_name"] = model_data.bcmdl_path
    MODELUPDATER = new_template["property"]["components"]["MODELUPDATER"]
    MODELUPDATER["functions"][0]["params"]["Param1"]["value"] = model_data.bcmdl_path

    # Update caption
    PICKABLE = new_template["property"]["components"]["PICKABLE"]
    PICKABLE["fields"]["fields"]["sOnPickCaption"] = pickup["caption"]
    PICKABLE["fields"]["fields"]["sOnPickTankUnknownCaption"] = pickup["caption"]

    # Update given item
    if len(pickup["resources"]) == 1:
        new_template = patch_single_item_pickup(new_template, pickup, pickup_id)
    else:
        new_template = patch_progressive_pickup(new_template, pickup, pickup_id)

    new_path = f"actors/items/randomizer_powerup/charclasses/randomizer_powerup_{pickup_id}.bmsad"
    editor.add_new_asset(new_path, Bmsad(new_template, editor.target_game), in_pkgs=pkgs_for_level)
    actor.oActorDefLink = f"actordef:{new_path}"

    # Powerup is in plain sight (except for the part we're using the sphere model)
    actor.pComponents.pop("LIFE", None)

    # Dependencies
    for level_pkg in pkgs_for_level:
        editor.ensure_present(level_pkg, "system/animtrees/base.bmsat")
        editor.ensure_present(level_pkg, "actors/items/itemsphere/charclasses/timeline.bmsas")
        for dep in model_data.dependencies:
            editor.ensure_present(level_pkg, dep)

    # For debugging, write the bmsad we just created
    _outpath.joinpath(f"randomizer_powerup_{pickup_id}.bmsad.json").write_text(
        json.dumps(new_template, indent=4)
    )
    for pkg in pkgs_for_level:
        editor.ensure_present(pkg, "actors/items/randomizer_powerup/scripts/randomizer_powerup.lc")


def patch_single_item_pickup(bmsad: dict, pickup: dict, pickup_id: int) -> dict:
    PICKABLE: dict = bmsad["property"]["components"]["PICKABLE"]
    SCRIPT: dict = bmsad["property"]["components"]["SCRIPT"]

    set_custom_params: dict = PICKABLE["functions"][0]["params"]
    item_id: str = pickup["resources"][0]["item_id"]
    quantity: float = pickup["resources"][0]["quantity"]

    if item_id == "ITEM_ENERGY_TANKS":
        item_id = "fMaxLife"
        quantity *= 100.0
        set_custom_params["Param4"]["value"] = "Full"
        set_custom_params["Param5"]["value"] = "fCurrentLife"
        set_custom_params["Param6"]["value"] = "LIFE"

    elif item_id == "ITEM_LIFE_SHARDS":
        item_id = "fLifeShards"
        set_custom_params["Param4"]["value"] = "Custom"
        set_custom_params["Param5"]["value"] = ""
        set_custom_params["Param6"]["value"] = "LIFE"
        set_custom_params["Param7"]["value"] = "#GUI_ITEM_ACQUIRED_ENERGY_SHARD"
        PICKABLE["fields"]["fields"]["sOnPickEnergyFragment1Caption"] = pickup["caption"]
        PICKABLE["fields"]["fields"]["sOnPickEnergyFragment2Caption"] = pickup["caption"]
        PICKABLE["fields"]["fields"]["sOnPickEnergyFragment3Caption"] = pickup["caption"]
        PICKABLE["fields"]["fields"]["sOnPickEnergyFragmentCompleteCaption"] = pickup["caption"]

    elif item_id in {"ITEM_WEAPON_MISSILE_MAX", "ITEM_WEAPON_POWER_BOMB_MAX", "ITEM_WEAPON_POWER_BOMB"}:
        current = item_id.replace("_MAX", "_CURRENT")
        if item_id == current:
            current += "_CURRENT"

        set_custom_params["Param4"]["value"] = "Custom"
        set_custom_params["Param5"]["value"] = current
        set_custom_params["Param8"]["value"] = "guicallbacks.OnSecondaryGunsFire"
        set_custom_params["Param13"] = {
            "type": "f",
            "value": quantity,
        }

    SCRIPT["functions"][0]["params"]["Param2"]["value"] = get_script_class(pickup)

    if item_id == "ITEM_WEAPON_POWER_BOMB":
        item_id = "ITEM_WEAPON_POWER_BOMB_MAX"

    set_custom_params["Param1"]["value"] = item_id
    set_custom_params["Param2"]["value"] = quantity

    return bmsad


expansions = {"ITEM_ENERGY_TANKS", "ITEM_LIFE_SHARDS", "ITEM_WEAPON_MISSILE_MAX", "ITEM_WEAPON_POWER_BOMB_MAX",
              "ITEM_WEAPON_POWER_BOMB"}


def patch_progressive_pickup(bmsad: dict, pickup: dict, pickup_id: int) -> dict:
    item_ids = {resource["item_id"] for resource in pickup["resources"]}
    if not expansions.isdisjoint(item_ids):
        raise NotImplementedError("Progressive pickups cannot include expansions.")

    PICKABLE: dict = bmsad["property"]["components"]["PICKABLE"]
    SCRIPT: dict = bmsad["property"]["components"]["SCRIPT"]

    set_custom_params: dict = PICKABLE["functions"][0]["params"]
    set_custom_params["Param1"]["value"] = "ITEM_NONE"

    SCRIPT["functions"][0]["params"]["Param2"]["value"] = get_script_class(pickup)

    return bmsad


_progressive_classes = {}


def get_script_class(pickup: dict, boss: bool = False) -> str:
    main_pb = pickup["resources"][0]["item_id"] == "ITEM_WEAPON_POWER_BOMB"
    if not boss and len(pickup["resources"]) == 1:
        return "RandomizerPowerBomb" if main_pb else "RandomizerPowerup"

    hashable_progression = "_".join([f'{res["item_id"]}_{res["quantity"]}' for res in pickup["resources"]])

    if hashable_progression in _progressive_classes.keys():
        return _progressive_classes[hashable_progression]

    class_name = f"RandomizerProgressive{hashable_progression}"

    resources = [
        {
            "item_id": lua_util.wrap_string(res["item_id"]),
            "quantity": res["quantity"]
        }
        for res in pickup["resources"]
    ]
    replacement = {
        "name": class_name,
        "progression": resources,
        "parent": "RandomizerPowerBomb" if main_pb else "RandomizerPowerup",
    }
    add_progressive_class(replacement)

    _progressive_classes[hashable_progression] = class_name
    return class_name


_powerup_script: str = None


def add_progressive_class(replacement):
    global _powerup_script
    if _powerup_script is None:
        _powerup_script = _read_powerup_lua()

    new_class = lua_util.replace_lua_template("randomizer_progressive_template.lua", replacement)
    _powerup_script += new_class.encode("utf-8")


def patch_emmi_pickup(editor: PatcherEditor, pickup: dict, pickup_id: int):
    bmsad_path, actordef = _patch_actordef_pickup(editor, pickup, pickup_id, "sInventoryItemOnKilled")
    editor.replace_asset(bmsad_path, actordef)


def patch_corex_pickup(editor: PatcherEditor, pickup: dict, pickup_id: int):
    bmsad_path, actordef = _patch_actordef_pickup(editor, pickup, pickup_id, "sInventoryItemOnBigXAbsorbed")
    editor.replace_asset(bmsad_path, actordef)


def patch_corpius_pickup(editor: PatcherEditor, pickup: dict, pickup_id: int):
    # TODO: fix weirdness with aeion suit upgrade thingy
    bmsad_path, actordef = _patch_actordef_pickup(editor, pickup, pickup_id, "sInventoryItemOnKilled")
    if pickup["resources"][0]["item_id"] not in expansions:
        actordef.raw["property"]["components"]["AI"]["fields"]["fields"]["bGiveInventoryItemOnDead"] = True

    editor.replace_asset(bmsad_path, actordef)


def _patch_actordef_pickup(editor: PatcherEditor, pickup: dict,
                           pickup_id: int, item_id_field: str) -> tuple[str, Bmsad]:
    item_id: str = pickup["resources"][0]["item_id"]

    if len(pickup["resources"]) > 1 or pickup["resources"][0]["quantity"] > 1 or item_id in expansions:
        item_id = "ITEM_NONE"
        _patch_actordef_pickup_script(editor, pickup)

    bmsad_path: str = pickup["pickup_actordef"]
    actordef = editor.get_file(bmsad_path, Bmsad)

    AI = actordef.raw["property"]["components"]["AI"]
    AI["fields"]["fields"][item_id_field] = item_id

    # may want to edit all the localization files?
    text_files = {
        # "eu_dutch.txt",
        # "eu_french.txt",
        # "eu_german.txt",
        # "eu_italian.txt",
        # "eu_spanish.txt",
        # "japanese.txt",
        # "korean.txt",
        # "russian.txt",
        # "simplified_chinese.txt",
        # "traditional_chinese.txt",
        "us_english.txt",
        # "us_french.txt",
        # "us_spanish.txt"
    }
    for text_file in text_files:
        text_file = "system/localization/" + text_file
        text = editor.get_file(text_file, Txt)
        text.strings[pickup["pickup_string_key"]] = pickup["caption"]
        editor.replace_asset(text_file, text)

    return bmsad_path, actordef


_custom_level_scripts: dict[str, str] = {}


def _patch_actordef_pickup_script(editor: PatcherEditor, pickup: dict):
    scenario: str = pickup["pickup_lua_callback"]["scenario"]

    scenario_path = path_for_level(scenario)
    lua_util.create_script_copy(editor, scenario_path)

    if scenario not in _custom_level_scripts.keys():
        _custom_level_scripts[scenario] = "\n".join([
            f"Game.LogWarn(0, 'Loading original {scenario}...')",
            f"Game.ImportLibrary('{scenario_path}_original.lua')",
            f"Game.LogWarn(0, 'Loaded original {scenario}.')",
            f"Game.DoFile('actors/items/randomizer_powerup/scripts/randomizer_powerup.lua')\n\n",
        ])

    replacement = {
        "scenario": scenario,
        "funcname": pickup["pickup_lua_callback"]["function"],
        "pickup_class": get_script_class(pickup, True),
        "args": ", ".join([f"_ARG_{i}_" for i in range(pickup["pickup_lua_callback"]["args"])])
    }
    _custom_level_scripts[scenario] += lua_util.replace_lua_template("boss_powerup_template.lua", replacement)


_outpath = Path()