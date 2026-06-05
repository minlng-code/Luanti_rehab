
-- add compatibility for ethereal nodes already added to default game or name changed

local aliases = {

	["ethereal:acacia_trunk"] = "default:acacia_tree",
	["ethereal:acacia_wood"] = "default:acacia_wood",
	["ethereal:fence_acacia"] = "default:fence_acacia_wood",
	["ethereal:fence_junglewood"] = "default:fence_junglewood",
	["ethereal:fence_pine"] = "default:fence_pine_wood",
	["ethereal:acacia_leaves"] = "default:acacia_leaves",
	["ethereal:pineleaves"] = "default:pine_needles",
	["ethereal:mushroom_craftingitem"] = "flowers:mushroom_brown",
	["ethereal:mushroom_plant"] = "flowers:mushroom_brown",
	["ethereal:mushroom_soup_cooked"] = "ethereal:mushroom_soup",
	["ethereal:mushroom_1"] = "flowers:mushroom_brown",
	["ethereal:mushroom_2"] = "flowers:mushroom_brown",
	["ethereal:mushroom_3"] = "flowers:mushroom_brown",
	["ethereal:mushroom_4"] = "flowers:mushroom_brown",
	["ethereal:strawberry_bush"] = "ethereal:strawberry_7",
	["ethereal:seed_strawberry"] = "ethereal:strawberry",
	["ethereal:wild_onion_1"] = "ethereal:onion_1",
	["ethereal:wild_onion_2"] = "ethereal:onion_2",
	["ethereal:wild_onion_3"] = "ethereal:onion_3",
	["ethereal:wild_onion_4"] = "ethereal:onion_4",
	["ethereal:wild_onion_5"] = "ethereal:onion_5",
	["ethereal:onion_7"] = "ethereal:onion_4",
	["ethereal:onion_8"] = "ethereal:onion_5",
	["ethereal:wild_onion_7"] = "ethereal:onion_4",
	["ethereal:wild_onion_8"] = "ethereal:onion_5",
	["ethereal:wild_onion_craftingitem"] = "ethereal:wild_onion_plant",
	["ethereal:hearty_stew_cooked"] = "ethereal:hearty_stew",
	["ethereal:obsidian_brick"] = "default:obsidianbrick",
	["ethereal:crystal_topped_dirt"] = "ethereal:crystal_dirt",
	["ethereal:fiery_dirt_top"] = "ethereal:fiery_dirt",
	["ethereal:gray_dirt_top"] = "ethereal:gray_dirt",
	["ethereal:green_dirt_top"] = "default;dirt_with_grass",
	["ethereal:tree_sapling"] = "default:sapling",
	["ethereal:jungle_tree_sapling"] = "default:junglesapling",
	["ethereal:acacia_sapling"] = "default:acacia_sapling",
	["ethereal:pine_tree_sapling"] = "default:pine_sapling",
}

for old_name, new_name in pairs(aliases) do
	core.register_alias(old_name, new_name)
end
