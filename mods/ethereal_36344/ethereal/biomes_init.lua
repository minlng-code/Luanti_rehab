
-- storage tables

local old_biomes, old_decor = {}, {}

-- backup registered biomes

for key, def in pairs(core.registered_biomes) do
	old_biomes[key] = def
end

-- backup registered decorations

for key, def in pairs(core.registered_decorations) do
	old_decor[key] = def
end

-- clear current biome data

core.clear_registered_biomes()
core.clear_registered_decorations()
-- core.clear_registered_ores()

-- list of default biomes to remove

local def_biomes = {
	["rainforest"] = 1,
	["rainforest_swamp"] = 1,
	["rainforest_ocean"] = 1,
	["rainforest_under"] = 1,
	["grassland"] = 1,
	["grassland_dunes"] = 1,
	["grassland_ocean"] = 1,
	["grassland_under"] = 1,
	["taiga"] = 1,
	["taiga_ocean"] = 1,
	["taiga_under"] = 1,
	["icesheet"] = 1,
	["icesheet_ocean"] = 1,
	["icesheet_under"] = 1,
	["snowy_grassland"] = 1,
	["snowy_grassland_ocean"] = 1,
	["snowy_grassland_under"] = 1,
	["desert"] = 1,
	["desert_ocean"] = 1,
	["desert_under"] = 1,
	["tundra"] = 1,
	["tundra_highland"] = 1,
	["tundra_beach"] = 1,
	["tundra_ocean"] = 1,
	["tundra_under"] = 1,
	["sandstone_desert"] = 1,
	["sandstone_desert_ocean"] = 1,
	["sandstone_desert_under"] = 1,
	["savanna"] = 1,
	["savanna_shore"] = 1,
	["savanna_ocean"] = 1,
	["savanna_under"] = 1,
	["cold_desert"] = 1,
	["cold_desert_ocean"] = 1,
	["cold_desert_under"] = 1,
	["coniferous_forest"] = 1,
	["coniferous_forest_dunes"] = 1,
	["coniferous_forest_ocean"] = 1,
	["coniferous_forest_under"] = 1,
	["deciduous_forest"] = 1,
	["deciduous_forest_shore"] = 1,
	["deciduous_forest_ocean"] = 1,
	["deciduous_forest_under"] = 1
}

-- only re-register biomes that aren't on the list

for key, def in pairs(old_biomes) do

	if not def_biomes[key] then core.register_biome(def) end
end

-- loop through decorations

for _, def in pairs(old_decor) do

	local biomes = type(def.biomes) == "table" and def.biomes or {def.biomes}
	local new_biomes = {}

	-- loop through decoration biomes, only re-add one's not on above list
	for _, bio in pairs(biomes) do
		if not def_biomes[bio] then table.insert(new_biomes, bio) end
	end

	if #new_biomes > 0 then
		core.register_decoration(def)
	end
end
