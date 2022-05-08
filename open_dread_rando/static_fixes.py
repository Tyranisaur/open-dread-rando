import copy

from open_dread_rando import door_patcher
from open_dread_rando.logger import LOG
from open_dread_rando.patcher_editor import PatcherEditor


def flip_icon_id(icon_id: str) -> str:
    if icon_id.endswith("R"):
        return icon_id[:-1] + "L"
    elif icon_id.endswith("L"):
        return icon_id[:-1] + "R"
    raise ValueError(f"Unable to flip icon {icon_id}")


def apply_one_sided_door_fixes(editor: PatcherEditor):
    all_scenarios = [
        "s010_cave",
        "s020_magma",
        "s030_baselab",
        "s040_aqua",
        "s050_forest",
        "s060_quarantine",
        "s070_basesanc",
        "s080_shipyard",
    ]

    for scenario_name in all_scenarios:
        scenario = editor.get_scenario(scenario_name)
        bmmap = editor.get_scenario_map(scenario_name)
        map_blockages = bmmap.raw.Root.mapBlockages

        for layer_name, actor_name, actor in list(scenario.all_actors()):
            if not door_patcher.is_door(actor):
                continue

            if actor.oActorDefLink != "actordef:actors/props/doorpowerpower/charclasses/doorpowerpower.bmsad":
                continue

            life_comp = actor.pComponents.LIFE
            left = scenario.follow_link(life_comp.wpLeftDoorShieldEntity)
            right = scenario.follow_link(life_comp.wpRightDoorShieldEntity)

            if left is None and right is None:
                continue

            elif left is None:
                other = right
                direction = "wpLeftDoorShieldEntity"

            elif right is None:
                other = left
                direction = "wpRightDoorShieldEntity"
            else:
                continue

            if "db_hdoor" in other.oActorDefLink:
                continue

            LOG.debug("%s/%s/%s: copy %s into %s", scenario_name, layer_name, actor_name, other.sName, direction)
            mirrored = copy.deepcopy(other)
            mirrored.sName += "_mirrored"
            mirrored.vAng = [other.vAng[0], -other.vAng[1], other.vAng[2]]
            scenario.actors_for_layer(layer_name)[mirrored.sName] = mirrored

            mirrored_map = copy.deepcopy(map_blockages[other.sName])
            mirrored_map["sIconId"] = flip_icon_id(mirrored_map["sIconId"])
            delta = 450 if mirrored_map["sIconId"].endswith("R") else -450
            mirrored_map["oBox"]["Min"][0] += delta
            mirrored_map["oBox"]["Max"][0] += delta
            map_blockages[mirrored.sName] = mirrored_map

            # Add a reference to the other shield to the main actor
            life_comp[direction] = f"Root:pScenario:rEntitiesLayer:dctSublayers:{layer_name}:dctActors:{mirrored.sName}"

            for group_name in scenario.all_actor_groups():
                if any(scenario.is_actor_in_group(group_name, x, layer_name) for x in [actor_name, other.sName]):
                    for name in [actor_name, mirrored.sName, other.sName]:
                        scenario.add_actor_to_group(group_name, name, layer_name)


PROBLEM_X_LAYERS = {
    "s010_cave": [
        "collision_camera_026",  # Chain reaction
        "collision_camera_020",  # Corpius arena
        "collision_camera_073",  # Corpius entrance
    ],
    "s020_magma": [
        "collision_camera_063",  # Kraid arena
    ],
    "s070_basesanc": [
        "collision_camera_005",  # Quiet Robe room
    ]
}


def remove_problematic_x_layers(editor: PatcherEditor):
    # these X layers have priority, so they will set some rooms to their post-state
    # even if they've never been entered. in these particular problem rooms, this
    # can cause softlocks (e.g. phantom cloak on golzuna, main PBs on corpius)
    for level, layers in PROBLEM_X_LAYERS.items():
        manager = editor.get_subarea_manager(level)
        configs = manager.get_subarea_setup("PostXRelease").vSubareaConfigs
        manager.get_subarea_setup("PostXRelease").vSubareaConfigs = [
            config for config in configs if config.sId not in layers
        ]


def add_callback_to_kraid(editor: PatcherEditor):
    magma = editor.get_scenario("s020_magma")
    death_cutscene_player = magma.follow_link(
        "Root:pScenario:rEntitiesLayer:dctSublayers:cutscenes:dctActors:cutsceneplayer_61"
    )
    death_cutscene_player.pComponents.CUTSCENE.vctOnAfterCutsceneEndsLA.append({
        "@type": "CLuaCallsLogicAction",
        "sCallbackEntityName": "",
        "sCallback": "CurrentScenario.OnKraidDeath_CUSTOM",
        "bCallbackEntity": False,
        "bCallbackPersistent": False,
    })


def activate_emmi_zones(editor: PatcherEditor):
    # Remove the cutscene that plays when you enter the emmi zone for the first time
    # This causes the border of the zone to not be revealed, but it should be possible to do that in another way
    editor.remove_entity(
        {
            "scenario": "s010_cave",
            "layer": "Cutscenes",
            "actor": "cutscenetrigger_36"
        },
        None,
    )

    # Remove the cutscene that introduces the speed emmi
    # This causes the border of the zone to not be revealed, but it should be possible to do that in another way
    editor.remove_entity(
        {
            "scenario": "s030_baselab",
            "layer": "cutscenes",
            "actor": "cutscenetrigger_39"
        },
        None,
    )


def apply_static_fixes(editor: PatcherEditor):
    remove_problematic_x_layers(editor)
    activate_emmi_zones(editor)
    apply_one_sided_door_fixes(editor)
    add_callback_to_kraid(editor)
