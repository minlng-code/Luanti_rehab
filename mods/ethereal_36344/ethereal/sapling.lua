
-- translator and protection check setting

local S = core.get_translator("ethereal")
local get_node = core.get_node
local sapling_protection_check = core.settings:get_bool(
		"ethereal.sapling_protection_check", false)

-- sapling placement helper

local function prepare_on_place(itemstack, placer, pointed_thing, name, w, h)

	if sapling_protection_check then

		-- check if grown tree area intersects any players protected area
		return default.sapling_on_place(itemstack, placer, pointed_thing,
				name, {x = -w, y = 1, z = -w}, {x = w, y = h, z = w}, 4)
	end

	-- Position of sapling
	local pos = pointed_thing.under
	local node = get_node(pos)
	local pdef = core.registered_nodes[node.name]

	-- Check if node clicked on has it's own on_rightclick function
	if pdef and pdef.on_rightclick
	and not (placer and placer:is_player() and placer:get_player_control().sneak) then
		return pdef.on_rightclick(pos, node, placer, itemstack, pointed_thing)
	end

	-- place normally
	return core.item_place_node(itemstack, placer, pointed_thing)
end

-- Bamboo Sprout

core.register_node("ethereal:bamboo_sprout", {
	description = S("Bamboo Sprout"),
	drawtype = "plantlike",
	tiles = {"ethereal_bamboo_sprout.png"},
	inventory_image = "ethereal_bamboo_sprout.png",
	wield_image = "ethereal_bamboo_sprout.png",
	paramtype = "light",
	sunlight_propagates = true,
	walkable = false,
	groups = {
		food_bamboo_sprout = 1, snappy = 3, attached_node = 1, flammable = 2,
		dig_immediate = 3, ethereal_sapling = 1, sapling = 1,
	},
	sounds = default.node_sound_defaults(),
	selection_box = {
		type = "fixed", fixed = {-3 / 16, -0.5, -3 / 16, 3 / 16, -0.1, 3 / 16}
	},
	on_use = core.item_eat(2),
	grown_height = 11,

	on_place = function(itemstack, placer, pointed_thing)
		return prepare_on_place(itemstack, placer, pointed_thing,
				"ethereal:bamboo_sprout", 1, 18)
	end
})

-- register Sapling helper

local function add_sapling(name, desc, texture, width, height)

	core.register_node("ethereal:" .. name .. "_sapling", {
		description = S(desc .. " Tree Sapling"),
		drawtype = "plantlike",
		tiles = {texture .. ".png"},
		inventory_image = texture .. ".png",
		wield_image = texture .. ".png",
		paramtype = "light",
		sunlight_propagates = true,
		is_ground_content = false,
		walkable = false,
		selection_box = {
			type = "fixed", fixed = {-4 / 16, -0.5, -4 / 16, 4 / 16, 5 / 16, 4 / 16}
		},
		groups = {
			snappy = 2, dig_immediate = 3, flammable = 2,
			ethereal_sapling = 1, attached_node = 1, sapling = 1
		},
		sounds = default.node_sound_leaves_defaults(),
		grown_height = height,

		on_place = function(itemstack, placer, pointed_thing)
			return prepare_on_place(itemstack, placer, pointed_thing,
					name .. "_sapling", width, height)
		end
	})
end

-- register saplings

add_sapling("basandra_bush", "Basandra Bush", "ethereal_basandra_bush_sapling", 1, 2)
add_sapling("mangrove", "Mangrove", "mcl_mangrove_propagule", 5, 14)
add_sapling("willow", "Willow", "ethereal_willow_sapling", 5, 14)
add_sapling("yellow_tree", "Healing", "ethereal_yellow_tree_sapling", 4, 19)
add_sapling("big_tree", "Big", "ethereal_big_tree_sapling", 4, 7)
add_sapling("banana_tree", "Banana", "ethereal_banana_tree_sapling", 3, 8)
add_sapling("frost_tree", "Frost", "ethereal_frost_tree_sapling", 4, 19)
add_sapling("mushroom", "Mushroom", "ethereal_mushroom_sapling", 4, 11)
add_sapling("mushroom_brown", "Brown Mushroom", "ethereal_mushroom_brown_sapling", 1, 11)
add_sapling("palm", "Palm", "moretrees_palm_sapling", 4, 9)
add_sapling("giant_redwood", "Giant Redwood", "ethereal_giant_redwood_sapling", 7, 33)
add_sapling("redwood", "Redwood", "ethereal_redwood_sapling", 4, 21)
add_sapling("orange_tree", "Orange", "ethereal_orange_tree_sapling", 2, 6)
add_sapling("birch", "Birch", "moretrees_birch_sapling", 2, 9)
add_sapling("sakura", "Sakura", "ethereal_sakura_sapling", 4, 10)
add_sapling("lemon_tree", "Lemon", "ethereal_lemon_tree_sapling", 2, 7)
add_sapling("olive_tree", "Olive", "ethereal_olive_tree_sapling", 3, 10)

-- add tree schematic

local function add_tree(pos, schem, replace)

	core.remove_node(pos)
	core.place_schematic(
			pos, schem, "random", replace, false, "place_center_x, place_center_z")
end

-- path to schematics folder

local path = core.get_modpath("ethereal") .. "/schematics/"

-- global tree grow functions

function ethereal.grow_mangrove_tree(pos)
	add_tree(pos, ethereal.mangrove_tree)
end

function ethereal.grow_basandra_bush(pos)
	add_tree(pos, ethereal.basandrabush)
end

function ethereal.grow_yellow_tree(pos)
	add_tree(pos, ethereal.yellowtree)
end

function ethereal.grow_big_tree(pos)
	add_tree(pos, ethereal.bigtree_from_sapling)
end

function ethereal.grow_banana_tree(pos)

	if math.random(2) == 1 and core.find_node_near(pos, 1, {"farming:soil_wet"}) then

		add_tree(pos, ethereal.bananatree, {{"ethereal:banana", "ethereal:banana_bunch"}})
	else
		add_tree(pos, ethereal.bananatree)
	end
end

function ethereal.grow_frost_tree(pos)
	add_tree(pos, ethereal.frosttrees_from_sapling)
end

function ethereal.grow_mushroom_tree(pos)
	add_tree(pos, ethereal.mushroomone_from_sapling)
end

function ethereal.grow_mushroom_brown_tree(pos)
	add_tree(pos, ethereal.mushroomtwo)
end

function ethereal.grow_palm_tree(pos)
	add_tree(pos, ethereal.palmtree)
end

function ethereal.grow_willow_tree(pos)
	add_tree(pos, ethereal.willow_from_sapling)
end

function ethereal.grow_redwood_tree(pos)
	add_tree(pos, ethereal.redwood_small_tree_from_sapling)
end

function ethereal.grow_giant_redwood_tree(pos)
	add_tree(pos, ethereal.redwood_tree_from_sapling)
end

function ethereal.grow_orange_tree(pos)
	add_tree(pos, ethereal.orangetree)
end

function ethereal.grow_bamboo_tree(pos)
	add_tree(pos, ethereal.bambootree)
end

function ethereal.grow_birch_tree(pos)

	if core.find_node_near(pos, 1, {"ethereal:magical_dirt"}) then

		local num = math.random(4)

		if num > 1 then
			add_tree(pos, ethereal.birchtree,
					{{"ethereal:birch_leaves", "ethereal:birch_leaves" .. num}})
			return
		end
	end

	add_tree(pos, ethereal.birchtree)
end

function ethereal.grow_sakura_tree(pos)

	if math.random(10) == 1 then

		add_tree(pos, ethereal.sakura_tree,
				{{"ethereal:sakura_leaves", "ethereal:sakura_leaves2"}})
	else
		add_tree(pos, ethereal.sakura_tree)
	end
end

function ethereal.grow_lemon_tree(pos)
	add_tree(pos, ethereal.lemontree)
end

function ethereal.grow_olive_tree(pos)
	add_tree(pos, ethereal.olivetree_from_sapling)
end

-- return True if sapling has enough height room to grow

local function enough_height(pos, height)

	return core.line_of_sight(
		{x = pos.x, y = pos.y + 1, z = pos.z},
		{x = pos.x, y = pos.y + height, z = pos.z})
end

-- global function run by Abm

function ethereal.grow_sapling(pos, node)

	-- sapling definition
	local def = core.registered_nodes[node and node.name] ; if not def then return end

	-- enough light to grow
	if (core.get_node_light(pos) or 0) < 13 then return end

	-- enought height to grow
	local height = def.grown_height or 33

	if not enough_height(pos, height) then return end

	-- get node below sapling
	local under =  get_node({x = pos.x, y = pos.y - 1, z = pos.z}).name

	-- default ok and magic dirt check (can grow any ethereal sapling)
	local ok = false ; if under == "ethereal:magical_dirt" then ok = true end

	-- check if Ethereal Sapling is growing on correct substrate
	if node.name == "ethereal:basandra_bush_sapling"
	and (under == "ethereal:fiery_dirt" or ok) then ethereal.grow_basandra_bush(pos)

	elseif node.name == "ethereal:yellow_tree_sapling"
	and core.get_item_group(under, "soil") > 0 then ethereal.grow_yellow_tree(pos)

	elseif node.name == "ethereal:big_tree_sapling"
	and (under == "default:dirt_with_grass" or ok) then ethereal.grow_big_tree(pos)

	elseif node.name == "ethereal:banana_tree_sapling"
	and (under == "ethereal:grove_dirt" or ok) then ethereal.grow_banana_tree(pos)

	elseif node.name == "ethereal:frost_tree_sapling"
	and (under == "ethereal:crystal_dirt" or ok) then ethereal.grow_frost_tree(pos)

	elseif node.name == "ethereal:mushroom_sapling"
	and (under == "ethereal:mushroom_dirt" or ok) then ethereal.grow_mushroom_tree(pos)

	elseif node.name == "ethereal:mushroom_brown_sapling"
	and (under == "ethereal:mushroom_dirt" or ok) then
			ethereal.grow_mushroom_brown_tree(pos)

	elseif node.name == "ethereal:palm_sapling"
	and (under == "default:sand" or ok) then ethereal.grow_palm_tree(pos)

	elseif node.name == "ethereal:willow_sapling"
	and (under == "ethereal:gray_dirt" or ok) then ethereal.grow_willow_tree(pos)

	elseif node.name == "ethereal:redwood_sapling"
	and (under == "default:dirt_with_dry_grass" or ok) then
			ethereal.grow_redwood_tree(pos)

	elseif node.name == "ethereal:giant_redwood_sapling"
	and (under == "default:dirt_with_dry_grass" or ok) then
			ethereal.grow_giant_redwood_tree(pos)

	elseif node.name == "ethereal:orange_tree_sapling"
	and (under == "ethereal:prairie_dirt" or ok) then ethereal.grow_orange_tree(pos)

	elseif node.name == "ethereal:bamboo_sprout"
	and (under == "ethereal:bamboo_dirt" or ok) then ethereal.grow_bamboo_tree(pos)

	elseif node.name == "ethereal:birch_sapling"
	and (under == "default:dirt_with_grass" or ok) then ethereal.grow_birch_tree(pos)

	elseif node.name == "ethereal:sakura_sapling"
	and (under == "ethereal:bamboo_dirt" or ok) then ethereal.grow_sakura_tree(pos)

	elseif node.name == "ethereal:olive_tree_sapling"
	and (under == "ethereal:grove_dirt" or ok) then ethereal.grow_olive_tree(pos)

	elseif node.name == "ethereal:mangrove_sapling"
	and (under == "ethereal:mud" or ok) then ethereal.grow_mangrove_tree(pos)

	elseif node.name == "ethereal:lemon_tree_sapling"
	and (under == "ethereal:grove_dirt" or ok) then ethereal.grow_lemon_tree(pos) end
end

-- grow saplings Abm

core.register_abm({
	label = "Ethereal grow sapling",
	nodenames = {"group:ethereal_sapling"},
	interval = 10,
	chance = 50,
	catch_up = false,
	action = ethereal.grow_sapling
})

-- 2x redwood saplings make 1x giant redwood sapling

core.register_craft({
	output = "ethereal:giant_redwood_sapling",
	recipe = {{"ethereal:redwood_sapling", "ethereal:redwood_sapling"}}
})
