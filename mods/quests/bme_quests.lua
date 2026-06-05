-- ============================================================
--  BME QUEST BANK — Full Progression System
--  Tương thích: mod "quests" by bell07 (ContentDB)
--  Game:        MineClone 5 / VoxeLibre (Luanti)
--
--  Cấu trúc:
--    Giai đoạn 1 — Thời kỳ Đồ Gỗ          (bme_p1:*)
--    Giai đoạn 2 — Thời kỳ Đồ Đá & Định cư (bme_p2:*)
--    Giai đoạn 3 — Kỷ nguyên Sắt            (bme_p3:*)
--    Giai đoạn 4 — Khám phá & Chiều khác    (bme_p4:*)
--    Giai đoạn 5 — Cuộc chiến cuối cùng     (bme_p5:*)
--    Nhánh Kỹ thuật                          (bme_tech:*)
--    Nhánh Giả kim & Phù phép                (bme_magic:*)
--    Nhánh Kinh tế & Xã hội                  (bme_trade:*)
--    Nhánh Khám phá Công trình               (bme_explore:*)
--    Nhánh Thành tựu ẩn                      (bme_secret:*)
-- ============================================================


-- ── HELPERS ─────────────────────────────────────────────────

local function give_reward(playername, itemname, count)
	-- core.after(0): trao item sau khi callback của quest hoàn tất hoàn toàn
	-- tránh xung đột inventory API trong lúc mod quests đang xử lý
	core.after(0, function()
		local player = core.get_player_by_name(playername)
		if not player then return end
		local inv   = player:get_inventory()
		local stack = ItemStack(itemname .. " " .. (count or 1))
		if inv:room_for_item("main", stack) then
			inv:add_item("main", stack)
			core.chat_send_player(playername,
				"§6[Phần thưởng]§r Nhận được: §e"
				.. (count or 1) .. "x " .. itemname)
		else
			local pos = player:get_pos()
			core.add_item(pos, stack)
			core.chat_send_player(playername,
				"§6[Phần thưởng]§r Túi đầy! Item rơi chân: §e"
				.. (count or 1) .. "x " .. itemname)
		end
	end)
end

local function give_rewards(playername, rewards)
	for _, r in ipairs(rewards) do
		give_reward(playername, r[1], r[2])
	end
end

local function phase_complete(playername, label)
	core.chat_send_player(playername, "")
	core.chat_send_player(playername, "§d╔══════════════════════════════╗")
	core.chat_send_player(playername, "§d║  §aGIAI ĐOẠN HOÀN THÀNH!      §d║")
	core.chat_send_player(playername, "§d║  §e" .. label)
	core.chat_send_player(playername, "§d╚══════════════════════════════╝")
	core.chat_send_player(playername, "")
end

local function quest_done(playername, msg)
	core.chat_send_player(playername, "§a✔ §r" .. msg)
end

-- core.after(0): thoát khỏi call stack callback trước khi start quest mới.
-- Khi autoaccept=true, mod quests gọi callback trong lúc đang xử lý
-- update_quest → start_quest ngay lập tức gây race condition, quest mới
-- bị nuốt mất hoặc không hiện lên HUD.
-- Guard kiểm tra trùng lặp: tránh start quest đã active hoặc đã xong.
local function unlock_next(playername, quest_id)
	core.after(0, function()
		local active  = quests.active_quests[playername]
		local success = quests.successfull_quests[playername]
		if (active  and active[quest_id])
		or (success and success[quest_id]) then
			return
		end
		quests.start_quest(playername, quest_id)
	end)
end


-- ── TRACKER STATE ─────────────────────────────────────────────
-- Theo dõi craft / kill / place khi API hook không đủ
local craft_trackers = {}
local kill_trackers  = {}
local place_trackers = {}

local function add_craft(p, item, n)
	craft_trackers[p] = craft_trackers[p] or {}
	craft_trackers[p][item] = (craft_trackers[p][item] or 0) + (n or 1)
end

local function add_kill(p)
	kill_trackers[p] = (kill_trackers[p] or 0) + 1
end
local function get_kills(p) return kill_trackers[p] or 0 end

local function add_place(p, item)
	place_trackers[p] = place_trackers[p] or {}
	place_trackers[p][item] = (place_trackers[p][item] or 0) + 1
end
local function get_place(p, item)
	return (place_trackers[p] and place_trackers[p][item]) or 0
end


-- ============================================================
--  GIAI ĐOẠN 1 — THỜI KỲ ĐỒ GỖ (The Primitive Age)
-- ============================================================

quests.register_quest("bme_p1:ben_re", {
	title       = "[GĐ1] Bén Rễ",
	description = "Thu thập 10 khối gỗ bất kỳ.\n§7Mục tiêu: Làm quen thao tác chặt cây.",
	max         = 10,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Bén Rễ hoàn thành!")
		give_rewards(p, { {"mcl_core:apple", 5} })
		unlock_next(p, "bme_p1:kheo_tay")
	end
})

quests.register_quest("bme_p1:kheo_tay", {
	title       = "[GĐ1] Khéo Tay",
	description = "Đặt 1 Bàn Chế Tạo (Crafting Table) xuống đất.\n§7Tập thao tác chọn và đặt vật phẩm.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Khéo Tay hoàn thành!")
		core.chat_send_player(p, "§b[Mở khóa]§r Công thức công cụ gỗ sẵn sàng!")
		unlock_next(p, "bme_p1:cong_cu_dau_tien")
	end
})

quests.register_quest("bme_p1:cong_cu_dau_tien", {
	title       = "[GĐ1] Công Cụ Đầu Tiên",
	description = "Chế tạo 1 Cuốc Gỗ (Wooden Pickaxe).\n§7Mở crafting table, xếp đúng công thức.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Công Cụ Đầu Tiên hoàn thành!")
		give_rewards(p, { {"mcl_torches:torch", 10} })
		unlock_next(p, "bme_p1:ke_san_moi")
	end
})

quests.register_quest("bme_p1:ke_san_moi", {
	title       = "[GĐ1] Kẻ Săn Mồi",
	description = "Thu thập 3 miếng thịt sống (từ lợn, bò, hoặc gà).\n§7Di chuyển và tương tác với sinh vật.",
	max         = 3,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Kẻ Săn Mồi hoàn thành!")
		give_rewards(p, { {"mcl_furnaces:furnace", 1} })
		phase_complete(p, "Thời kỳ Đồ Gỗ hoàn thành!")
		unlock_next(p, "bme_p2:cung_cap")
	end
})


-- ============================================================
--  GIAI ĐOẠN 2 — THỜI KỲ ĐỒ ĐÁ & ĐỊNH CƯ (The Stone Age)
-- ============================================================

quests.register_quest("bme_p2:cung_cap", {
	title       = "[GĐ2] Cứng Cáp",
	description = "Khai thác 20 khối Đá Cuội (Cobblestone).\n§7Tăng sức bền tay với vật liệu cứng hơn.",
	max         = 20,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Cứng Cáp hoàn thành!")
		core.chat_send_player(p, "§b[Mở khóa]§r Công thức công cụ đá!")
		unlock_next(p, "bme_p2:anh_sang_bong_toi")
	end
})

quests.register_quest("bme_p2:anh_sang_bong_toi", {
	title       = "[GĐ2] Ánh Sáng Bóng Tối",
	description = "Tìm và khai thác 5 quặng Than (Coal Ore).\n§7Xuống hang tối — luyện điều hướng không gian 3D.",
	max         = 5,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Ánh Sáng Bóng Tối hoàn thành!")
		give_rewards(p, { {"mcl_core:coal_lump", 5} })
		unlock_next(p, "bme_p2:tho_ren_so_cap")
	end
})

quests.register_quest("bme_p2:tho_ren_so_cap", {
	title       = "[GĐ2] Thợ Rèn Sơ Cấp",
	description = "Chế tạo 1 Cuốc Đá (Stone Pickaxe).\n§7Kết hợp nguyên liệu từ hai nhiệm vụ trước.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Thợ Rèn Sơ Cấp hoàn thành!")
		give_rewards(p, { {"mcl_buckets:bucket_water", 1} })
		unlock_next(p, "bme_p2:nong_trai_nho")
	end
})

quests.register_quest("bme_p2:nong_trai_nho", {
	title       = "[GĐ2] Nông Trại Nhỏ",
	description = "Trồng 5 hạt giống lúa mì (Wheat Seeds) trên đất cày.\n§7Thao tác chính xác: cày đất rồi đặt hạt đúng vị trí.",
	max         = 5,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Nông Trại Nhỏ hoàn thành!")
		give_rewards(p, { {"mcl_farming:hoe_wood", 1} })
		phase_complete(p, "Thời kỳ Đồ Đá & Định cư hoàn thành!")
		unlock_next(p, "bme_p3:lua_ren")
		unlock_next(p, "bme_tech:ky_su_so_cap")   -- Mở nhánh kỹ thuật
	end
})


-- ============================================================
--  GIAI ĐOẠN 3 — KỶ NGUYÊN SẮT & CÔNG NGHỆ (The Iron Age)
-- ============================================================

quests.register_quest("bme_p3:lua_ren", {
	title       = "[GĐ3] Lửa Rèn",
	description = "Nung chảy 10 thỏi Sắt (Iron Ingots) trong lò.\n§7Đào quặng sắt → bỏ lò → đợi → lấy ra.",
	max         = 10,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Lửa Rèn hoàn thành!")
		core.chat_send_player(p, "§b[Mở khóa]§r Công thức Giáp Sắt!")
		unlock_next(p, "bme_p3:tho_mo_chuyen_nghiep")
	end
})

quests.register_quest("bme_p3:tho_mo_chuyen_nghiep", {
	title       = "[GĐ3] Thợ Mỏ Chuyên Nghiệp",
	description = "Chế tạo 1 Cuốc Sắt (Iron Pickaxe).\n§7Công cụ mở ra tầng khoáng sản sâu hơn.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Thợ Mỏ Chuyên Nghiệp hoàn thành!")
		give_rewards(p, { {"mcl_core:gold_ingot", 2} })
		unlock_next(p, "bme_p3:nang_luong_tho")
	end
})

quests.register_quest("bme_p3:nang_luong_tho", {
	title       = "[GĐ3] Năng Lượng Thô",
	description = "Thu thập 8 bột Redstone (hoặc 4 mảnh Mese).\n§7Nằm sâu dưới lòng đất — phải xuống hang tối.",
	max         = 8,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Năng Lượng Thô hoàn thành!")
		give_rewards(p, { {"mesecons_pistons:piston_normal_off", 1} })
		unlock_next(p, "bme_p3:bao_ho")
		unlock_next(p, "bme_tech:logictician")   -- Mở Mesecons nâng cao
	end
})

quests.register_quest("bme_p3:bao_ho", {
	title       = "[GĐ3] Bảo Hộ",
	description = "Chế tạo đủ 4 mảnh Giáp Sắt (Mũ + Áo + Quần + Giày).\n§7Thử thách craft phức tạp nhất từ trước đến nay.",
	max         = 4,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Bảo Hộ hoàn thành!")
		give_rewards(p, { {"mcl_weapons:sword_iron", 1} })
		phase_complete(p, "Kỷ nguyên Sắt hoàn thành!")
		unlock_next(p, "bme_p4:ke_tim_vang")
		unlock_next(p, "bme_magic:nha_thong_thai")  -- Mở nhánh phù phép
		unlock_next(p, "bme_trade:thuong_nhan")      -- Mở nhánh thương mại
	end
})


-- ============================================================
--  GIAI ĐOẠN 4 — KHÁM PHÁ & CHIỀU KHÔNG GIAN KHÁC (Exploration)
-- ============================================================

quests.register_quest("bme_p4:ke_tim_vang", {
	title       = "[GĐ4] Kẻ Tìm Vàng",
	description = "Đào 5 quặng Vàng ở độ sâu y < -100.\n§7Xuống thật sâu — rèn luyện di chuyển không gian phức tạp.",
	max         = 5,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Kẻ Tìm Vàng hoàn thành!")
		give_rewards(p, { {"mcl_core:diamond", 5} })
		unlock_next(p, "bme_p4:do_cung_vinh_cuu")
	end
})

quests.register_quest("bme_p4:do_cung_vinh_cuu", {
	title       = "[GĐ4] Độ Cứng Vĩnh Cửu",
	description = "Khai thác 10 khối Obsidian (Hắc Diện Thạch).\n§7Cần cuốc kim cương — tốc độ đào rất chậm, cần kiên nhẫn.",
	max         = 10,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Độ Cứng Vĩnh Cửu hoàn thành!")
		core.chat_send_player(p, "§b[Mở khóa]§r Công thức Cổng Nether!")
		unlock_next(p, "bme_p4:tho_san_quai_vat")
	end
})

quests.register_quest("bme_p4:tho_san_quai_vat", {
	title       = "[GĐ4] Thợ Săn Quái Vật",
	description = "Tiêu diệt 10 quái vật thù địch (Zombie, Creeper, Skeleton...).\n§7Phản xạ nhanh, di chuyển linh hoạt, phối hợp tay-mắt cao độ.",
	max         = 10,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Thợ Săn Quái Vật hoàn thành!")
		give_rewards(p, { {"mcl_potions:potion_swiftness", 1} })
		unlock_next(p, "bme_p4:vua_trang_bi")
	end
})

quests.register_quest("bme_p4:vua_trang_bi", {
	title       = "[GĐ4] Vua Trang Bị",
	description = "Chế tạo ít nhất 1 món đồ bằng Kim Cương (công cụ hoặc giáp).\n§7Đỉnh cao của hành trình chế tạo!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Vua Trang Bị hoàn thành!")
		give_rewards(p, { {"mcl_enchanting:book_enchanted", 1} })
		phase_complete(p, "Giai đoạn Khám Phá hoàn thành!")
		unlock_next(p, "bme_p5:mat_than")
		unlock_next(p, "bme_explore:ke_cuop_mo")  -- Mở nhánh khám phá
	end
})


-- ============================================================
--  GIAI ĐOẠN 5 — CUỘC CHIẾN CUỐI CÙNG (The End Game)
-- ============================================================

quests.register_quest("bme_p5:mat_than", {
	title       = "[GĐ5] Mắt Thần",
	description = "Thu thập hoặc chế tạo 12 Mắt Ender (Ender Eyes).\n§7Cần: Blaze Powder + Ender Pearl — mỗi thứ có hành trình riêng.",
	max         = 12,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Mắt Thần hoàn thành!")
		core.chat_send_player(p, "§b[Mở khóa]§r Cổng End có thể kích hoạt!")
		unlock_next(p, "bme_p5:hanh_trinh_cuoi")
	end
})

quests.register_quest("bme_p5:hanh_trinh_cuoi", {
	title       = "[GĐ5] Hành Trình Cuối",
	description = "Bước vào chiều không gian End (The End).\n§7Chuẩn bị thật kỹ — không quay đầu được!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "Hành Trình Cuối hoàn thành!")
		give_rewards(p, {
			{"mcl_bows:bow", 1},
			{"mcl_core:arrow", 64},
		})
		unlock_next(p, "bme_p5:huyen_thoai")
	end
})

quests.register_quest("bme_p5:huyen_thoai", {
	title       = "[GĐ5] ★ HUYỀN THOẠI — Ender Dragon",
	description = "Tiêu diệt Ender Dragon (hoặc Boss tương đương).\n§7Thử thách vĩ đại nhất trong hành trình phục hồi!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		give_rewards(p, { {"mcl_end:elytra", 1} })
		core.chat_send_player(p, "")
		core.chat_send_player(p, "§6★★★★★★★★★★★★★★★★★★★★★★★★★★★")
		core.chat_send_player(p, "§a   CHÚC MỪNG, HUYỀN THOẠI!")
		core.chat_send_player(p, "§e   Danh hiệu: §d\"The Savior\"")
		core.chat_send_player(p, "§7   Toàn bộ hành trình phục hồi BME hoàn thành.")
		core.chat_send_player(p, "§7   Hãy báo cáo bác sĩ để ghi nhận kết quả!")
		core.chat_send_player(p, "§6★★★★★★★★★★★★★★★★★★★★★★★★★★★")
		-- TODO: Gọi API Firebase ghi nhận 7 tham số phục hồi
	end
})


-- ============================================================
--  NHÁNH KỸ THUẬT — Mesecons / Redstone
--  Mở sau GĐ2
-- ============================================================

quests.register_quest("bme_tech:ky_su_so_cap", {
	title       = "[Tech] Kỹ Sư Sơ Cấp",
	description = "Xây hệ thống cửa tự động bằng Pressure Plate + Mesecon.\n§7Đặt: tấm áp lực → dây → cánh cửa. Bước lên để kiểm tra!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Tech] Kỹ Sư Sơ Cấp hoàn thành!")
		give_rewards(p, { {"mesecons:wire_00000000_off", 16} })
	end
})

quests.register_quest("bme_tech:logictician", {
	title       = "[Tech] Logictician",
	description = "Xây cổng logic AND hoặc OR bằng Mesecons.\n§7Hai tín hiệu vào → một đầu ra → mở kho báu bí mật!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Tech] Logictician hoàn thành!")
		give_rewards(p, {
			{"mcl_core:chest", 1},
			{"mcl_core:diamond", 3},
		})
		unlock_next(p, "bme_tech:bang_chuyen")
	end
})

quests.register_quest("bme_tech:bang_chuyen", {
	title       = "[Tech] Băng Chuyền Thần Tốc",
	description = "Tạo hệ thống phân loại tự động: ít nhất 2 Hopper nối 2 rương.\n§7Kết hợp Hopper + đường ray để tự động chuyển đồ.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Tech] Băng Chuyền hoàn thành!")
		give_rewards(p, {
			{"mcl_minecarts:rail", 32},
			{"mcl_hoppers:hopper", 4},
		})
	end
})


-- ============================================================
--  NHÁNH GIẢ KIM & PHÙ PHÉP — Magic & Alchemy
--  Mở sau GĐ3
-- ============================================================

quests.register_quest("bme_magic:nha_thong_thai", {
	title       = "[Magic] Nhà Thông Thái",
	description = "Xây Bàn Phù Phép (Enchanting Table) và đạt Level 30 XP.\n§7Chiến đấu và khai thác để tích lũy kinh nghiệm.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Magic] Nhà Thông Thái hoàn thành!")
		give_rewards(p, { {"mcl_enchanting:book_enchanted", 2} })
		unlock_next(p, "bme_magic:duoc_si")
	end
})

quests.register_quest("bme_magic:duoc_si", {
	title       = "[Magic] Dược Sĩ",
	description = "Pha chế 1 bình thuốc Tăng Tốc (Swiftness) hoặc Hồi Máu (Healing).\n§7Cần Brewing Stand + Nether Wart + nguyên liệu đặc biệt.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Magic] Dược Sĩ hoàn thành!")
		give_rewards(p, {
			{"mcl_potions:potion_healing",   2},
			{"mcl_potions:potion_swiftness", 2},
		})
		unlock_next(p, "bme_magic:vu_khi_huyen_thoai")
	end
})

quests.register_quest("bme_magic:vu_khi_huyen_thoai", {
	title       = "[Magic] Vũ Khí Huyền Thoại",
	description = "Phù phép một món đồ đạt cấp độ cao (Fortune, Mending, Sharpness...).\n§7Dùng Bàn Phù Phép + sách để tạo vũ khí tối thượng.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Magic] Vũ Khí Huyền Thoại hoàn thành!")
		give_rewards(p, {
			{"mcl_weapons:sword_diamond", 1},
			{"mcl_core:diamond",          5},
		})
	end
})


-- ============================================================
--  NHÁNH KINH TẾ & XÃ HỘI — Trading & Settlement
--  Mở sau GĐ3
-- ============================================================

quests.register_quest("bme_trade:thuong_nhan", {
	title       = "[Trade] Thương Nhân",
	description = "Thực hiện 10 giao dịch với Dân Làng (Villagers).\n§7Tìm làng → tương tác NPC → đổi hàng hóa.",
	max         = 10,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Trade] Thương Nhân hoàn thành!")
		give_rewards(p, { {"mcl_core:emerald", 16} })
		unlock_next(p, "bme_trade:tien_te")
		unlock_next(p, "bme_trade:nguoi_bao_ve")
	end
})

quests.register_quest("bme_trade:tien_te", {
	title       = "[Trade] Tiền Tệ",
	description = "Tích lũy 64 viên Lục Bảo (Emerald) qua bán nông sản.\n§7Kết hợp: trồng trọt → thu hoạch → giao dịch → tích lũy.",
	max         = 64,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Trade] Tiền Tệ hoàn thành!")
		give_rewards(p, {
			{"mcl_core:diamond",  8},
			{"mcl_core:emerald", 32},
		})
	end
})

quests.register_quest("bme_trade:nguoi_bao_ve", {
	title       = "[Trade] Người Bảo Vệ",
	description = "Đẩy lùi một cuộc Đột Kích (Raid) của đám cướp.\n§7Chiến đấu liên tục nhiều đợt — sức bền và phản xạ tổng hợp!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Trade] Người Bảo Vệ hoàn thành!")
		core.chat_send_player(p, "§6[Danh hiệu]§r §aAnh Hùng Làng§r đã được ghi nhận!")
		give_rewards(p, {
			{"mcl_potions:potion_strength", 2},
			{"mcl_core:emerald",            32},
		})
	end
})


-- ============================================================
--  NHÁNH KHÁM PHÁ CÔNG TRÌNH — Exploration & Structure
--  Mở sau GĐ4
-- ============================================================

quests.register_quest("bme_explore:ke_cuop_mo", {
	title       = "[Explore] Kẻ Cướp Mộ",
	description = "Tìm kho báu trong Đền Thờ Sa Mạc (Desert Temple).\n§7Đào xuống giữa sàn — cẩn thận bẫy TNT!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Explore] Kẻ Cướp Mộ hoàn thành!")
		give_rewards(p, {
			{"mcl_core:diamond",    4},
			{"mcl_core:gold_ingot", 8},
		})
		unlock_next(p, "bme_explore:thuyen_truong")
	end
})

quests.register_quest("bme_explore:thuyen_truong", {
	title       = "[Explore] Thuyền Trưởng",
	description = "Khám phá Con Tàu Đắm (Shipwreck) dưới đáy biển.\n§7Lặn sâu — chú ý thanh oxy và di chuyển dưới nước.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Explore] Thuyền Trưởng hoàn thành!")
		give_rewards(p, {
			{"mcl_potions:potion_water_breathing", 2},
			{"mcl_core:diamond",                   3},
		})
		unlock_next(p, "bme_explore:phao_dai_co")
		unlock_next(p, "bme_explore:vuon_treo")
	end
})

quests.register_quest("bme_explore:phao_dai_co", {
	title       = "[Explore] Pháo Đài Cổ",
	description = "Tìm Stronghold và kích hoạt Cổng End bằng Mắt Ender.\n§7Dùng Ender Eye để định hướng — đi theo hướng nó rơi.",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Explore] Pháo Đài Cổ hoàn thành!")
		give_rewards(p, { {"mcl_end:ender_eye", 4} })
	end
})

quests.register_quest("bme_explore:vuon_treo", {
	title       = "[Explore] Vườn Treo",
	description = "Tìm rừng nhiệt đới (Jungle) và thu thập 8 Hạt Cacao.\n§7Di chuyển xa, khám phá địa hình đa dạng.",
	max         = 8,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Explore] Vườn Treo hoàn thành!")
		give_rewards(p, { {"mcl_farming:cocoa_beans", 16} })
	end
})


-- ============================================================
--  NHÁNH THÀNH TỰU ẨN — Secret Achievements
-- ============================================================

quests.register_quest("bme_secret:ke_chinh_phuc_bau_troi", {
	title       = "[Bí ẩn] Kẻ Chinh Phục Bầu Trời",
	description = "Sở hữu Elytra và bay trong không trung.\n§7Dùng Elytra + Pháo hoa để lượn — thử thách khéo léo tổng hợp!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Bí ẩn] Kẻ Chinh Phục Bầu Trời hoàn thành!")
		give_rewards(p, { {"mcl_fireworks:firework_rocket", 16} })
		unlock_next(p, "bme_secret:ngon_hai_dang")
	end
})

quests.register_quest("bme_secret:ngon_hai_dang", {
	title       = "[Bí ẩn] Ngọn Hải Đăng",
	description = "Xây dựng và kích hoạt Beacon cấp 4 (tối đa).\n§7Cần 81 khối khoáng sản + Nether Star — thử thách tổng lực!",
	max         = 1,
	autoaccept  = true,
	callback    = function(p)
		quest_done(p, "[Bí ẩn] Ngọn Hải Đăng hoàn thành!")
		give_rewards(p, {
			{"mcl_core:diamond_block", 3},
			{"mcl_core:gold_block",    3},
		})
	end
})


-- ============================================================
--  NODE NAME LOOKUP TABLES
--  Liệt kê chính xác, đầy đủ theo source VoxeLibre / MineClone5
--  Bao gồm: mọi biome, deepslate (y<0), nether variants
-- ============================================================

-- GỖ: tất cả 7 loại cây + mangrove + cherry blossom (mod optional)
-- Mỗi loại có 2 hướng: trục Y (đứng) và trục X/Z (ngang khi đổ)
local WOOD_NODES = {
	-- Oak
	"mcl_core:tree",         "mcl_core:tree_top",
	-- Birch  ← hay bị thiếu nhất
	"mcl_core:birchtree",    "mcl_core:birchtree_top",
	-- Spruce ← hay bị thiếu nhất
	"mcl_core:sprucetree",   "mcl_core:sprucetree_top",
	-- Jungle
	"mcl_core:jungletree",   "mcl_core:jungletree_top",
	-- Acacia
	"mcl_core:acaciatree",   "mcl_core:acaciatree_top",
	-- Dark Oak
	"mcl_core:darkoaktree",  "mcl_core:darkoaktree_top",
	-- Mangrove
	"mcl_mangrove:mangrove_log",
	"mcl_mangrove:mangrove_roots",
	"mcl_mangrove:mangrove_roots_dry",
	-- Cherry Blossom (mod mcl_cherry_blossom nếu có)
	"mcl_cherry_blossom:cherry_blossom_log",
	-- Stripped logs (dùng rìu lột vỏ — vẫn tính là gỗ)
	"mcl_core:stripped_oak_log",
	"mcl_core:stripped_birch_log",
	"mcl_core:stripped_spruce_log",
	"mcl_core:stripped_jungle_log",
	"mcl_core:stripped_acacia_log",
	"mcl_core:stripped_dark_oak_log",
}
local WOOD_SET = {}
for _, v in ipairs(WOOD_NODES) do WOOD_SET[v] = true end

-- ĐÁ: stone + cobblestone + đá biến thể + deepslate
local STONE_NODES = {
	"mcl_core:stone",        "mcl_core:cobble",
	"mcl_core:andesite",     "mcl_core:andesite_smooth",
	"mcl_core:diorite",      "mcl_core:diorite_smooth",
	"mcl_core:granite",      "mcl_core:granite_smooth",
	"mcl_core:stonebrick",   "mcl_core:mossycobble",
	"mcl_core:mossystonebrick",
	-- Deepslate (xuất hiện từ y < 0)
	"mcl_deepslate:deepslate",
	"mcl_deepslate:cobbled_deepslate",
	"mcl_deepslate:deepslate_bricks",
	"mcl_deepslate:deepslate_tiles",
	"mcl_deepslate:chiseled_deepslate",
	"mcl_deepslate:polished_deepslate",
	-- Tuff (xuất hiện cùng deepslate)
	"mcl_deepslate:tuff",
	-- Calcite
	"mcl_deepslate:calcite",
}
local STONE_SET = {}
for _, v in ipairs(STONE_NODES) do STONE_SET[v] = true end

-- THAN: stone + deepslate variants
local COAL_NODES = {
	"mcl_core:stone_with_coal",
	"mcl_deepslate:deepslate_with_coal",
}
local COAL_SET = {}
for _, v in ipairs(COAL_NODES) do COAL_SET[v] = true end

-- QUẶNG SẮT: stone + deepslate
local IRON_NODES = {
	"mcl_core:stone_with_iron",
	"mcl_deepslate:deepslate_with_iron",
}
local IRON_SET = {}
for _, v in ipairs(IRON_NODES) do IRON_SET[v] = true end

-- QUẶNG VÀNG: stone + deepslate + nether gold
local GOLD_NODES = {
	"mcl_core:stone_with_gold",
	"mcl_deepslate:deepslate_with_gold",
	"mcl_nether:nether_gold_ore",  -- Nether gold (drop nugget)
}
local GOLD_SET = {}
for _, v in ipairs(GOLD_NODES) do GOLD_SET[v] = true end

-- QUẶNG ĐỒNG: stone + deepslate (1.17+)
local COPPER_NODES = {
	"mcl_copper:stone_with_copper",
	"mcl_copper:deepslate_with_copper",
	"mcl_deepslate:deepslate_with_copper",
	"mcl_core:stone_with_copper",          -- tên thay thế tùy bản
}
local COPPER_SET = {}
for _, v in ipairs(COPPER_NODES) do COPPER_SET[v] = true end

-- KIM CƯƠNG: stone + deepslate
local DIAMOND_NODES = {
	"mcl_core:stone_with_diamond",
	"mcl_deepslate:deepslate_with_diamond",
}
local DIAMOND_SET = {}
for _, v in ipairs(DIAMOND_NODES) do DIAMOND_SET[v] = true end

-- REDSTONE: stone + deepslate (2 trạng thái sáng/tối)
local REDSTONE_NODES = {
	"mcl_core:stone_with_redstone",
	"mcl_core:stone_with_redstone_lit",
	"mcl_deepslate:deepslate_with_redstone",
	"mcl_deepslate:deepslate_with_redstone_lit",
}
local REDSTONE_SET = {}
for _, v in ipairs(REDSTONE_NODES) do REDSTONE_SET[v] = true end

-- EMERALD: stone + deepslate
local EMERALD_NODES = {
	"mcl_core:stone_with_emerald",
	"mcl_deepslate:deepslate_with_emerald",
}
local EMERALD_SET = {}
for _, v in ipairs(EMERALD_NODES) do EMERALD_SET[v] = true end

-- THÚ VẬT cho quest "Kẻ săn mồi"
local ANIMAL_MOBS = {
	"mobs_mc:pig",     "mobs_mc:cow",
	"mobs_mc:chicken", "mobs_mc:sheep",
	"mobs_mc:rabbit",  "mobs_mc:cod",
	"mobs_mc:salmon",
}
local ANIMAL_SET = {}
for _, v in ipairs(ANIMAL_MOBS) do ANIMAL_SET[v] = true end

-- QUÁI VẬT THÙ ĐỊCH cho quest "Thợ săn quái vật"
local HOSTILE_MOBS = {
	"mobs_mc:zombie",          "mobs_mc:creeper",
	"mobs_mc:skeleton",        "mobs_mc:spider",
	"mobs_mc:cave_spider",     "mobs_mc:enderman",
	"mobs_mc:blaze",           "mobs_mc:ghast",
	"mobs_mc:witch",           "mobs_mc:husk",
	"mobs_mc:stray",           "mobs_mc:drowned",
	"mobs_mc:silverfish",      "mobs_mc:zombie_pigman",
	"mobs_mc:zombified_piglin","mobs_mc:piglin",
	"mobs_mc:hoglin",          "mobs_mc:zoglin",
	"mobs_mc:phantom",         "mobs_mc:slime",
	"mobs_mc:magma_cube",      "mobs_mc:wither_skeleton",
}
local HOSTILE_SET = {}
for _, v in ipairs(HOSTILE_MOBS) do HOSTILE_SET[v] = true end

-- PILLAGER / RAID MOBS cho quest "Người bảo vệ"
local RAID_MOBS = {
	"mobs_mc:pillager",  "mobs_mc:vindicator",
	"mobs_mc:ravager",   "mobs_mc:evoker",
	"mobs_mc:witch",     -- witch xuất hiện trong raid
}
local RAID_SET = {}
for _, v in ipairs(RAID_MOBS) do RAID_SET[v] = true end


-- ============================================================
--  SAFE UPDATE HELPER
--  Bọc quests.update_quest với kiểm tra: chỉ update khi quest
--  đang active. Tránh gọi update trên quest chưa start hoặc
--  đã hoàn thành — nguyên nhân phụ gây callback bị trigger sai.
-- ============================================================
local function safe_update(playername, quest_id, amount)
	local active = quests.active_quests[playername]
	if active and active[quest_id] and not active[quest_id].finished then
		quests.update_quest(playername, quest_id, amount or 1)
	end
end


-- ============================================================
--  EVENT LISTENERS
-- ============================================================

-- ── ĐÀO KHỐI ─────────────────────────────────────────────────
core.register_on_dignode(function(pos, oldnode, digger)
	if not digger or not digger:is_player() then return end
	local p    = digger:get_player_name()
	local name = oldnode.name

	-- ── GỖ (mọi loại cây, mọi biome) → GĐ1: Bén rễ ──────────
	if WOOD_SET[name] then
		safe_update(p, "bme_p1:ben_re", 1)
	end

	-- ── ĐÁ (stone, cobble, deepslate...) → GĐ2: Cứng cáp ─────
	if STONE_SET[name] then
		safe_update(p, "bme_p2:cung_cap", 1)
	end

	-- ── THAN (stone + deepslate) → GĐ2: Ánh sáng bóng tối ────
	if COAL_SET[name] then
		safe_update(p, "bme_p2:anh_sang_bong_toi", 1)
	end

	-- ── REDSTONE (stone + deepslate) → GĐ3: Năng lượng thô ───
	if REDSTONE_SET[name] then
		safe_update(p, "bme_p3:nang_luong_tho", 1)
	end

	-- ── VÀNG → GĐ4: Kẻ tìm vàng (cần y < -100) ───────────────
	if GOLD_SET[name] then
		-- Nether gold không cần kiểm tra độ sâu
		if name == "mcl_nether:nether_gold_ore" then
			safe_update(p, "bme_p4:ke_tim_vang", 1)
		elseif pos.y < -100 then
			safe_update(p, "bme_p4:ke_tim_vang", 1)
		else
			core.chat_send_player(p,
				"§e[Gợi ý]§r Vàng này không đủ sâu (y="
				.. math.floor(pos.y) .. "). Cần xuống dưới y=-100!")
		end
	end

	-- ── OBSIDIAN → GĐ4: Độ cứng vĩnh cửu ─────────────────────
	if name == "mcl_core:obsidian"
	or name == "mcl_core:crying_obsidian" then   -- crying obsidian cũng tính
		safe_update(p, "bme_p4:do_cung_vinh_cuu", 1)
	end

	-- ── KIM CƯƠNG → GĐ4: Vua trang bị (theo dõi để kiểm tra sau)
	-- (quest vua_trang_bi trigger từ craft, không phải đào)

	-- ── EMERALD → Trade: Tiền tệ ──────────────────────────────
	if EMERALD_SET[name] then
		safe_update(p, "bme_trade:tien_te", 1)
	end

	-- ── CACAO chín → Explore: Vườn treo ───────────────────────
	-- Stage 2 và 3 đều harvest được
	if name == "mcl_farming:cocoa_3"
	or name == "mcl_farming:cocoa_2" then
		safe_update(p, "bme_explore:vuon_treo", 1)
	end
end)


-- ── ĐẶT KHỐI ─────────────────────────────────────────────────
core.register_on_placenode(function(pos, newnode, placer, oldnode, itemstack)
	if not placer or not placer:is_player() then return end
	local p    = placer:get_player_name()
	local name = newnode.name

	-- CRAFTING TABLE → GĐ1: Khéo tay
	-- Tên thực tế trong VoxeLibre là mcl_crafting:workbench
	if name == "mcl_crafting:workbench" then
		safe_update(p, "bme_p1:kheo_tay", 1)
	end

	-- HẠT GIỐNG → GĐ2: Nông trại nhỏ
	-- Bao gồm đầy đủ: lúa mì, cà rốt, khoai tây, củ cải, bí đỏ, dưa hấu
	if name == "mcl_farming:wheat_0"
	or name == "mcl_farming:carrot_1"
	or name == "mcl_farming:potato_1"
	or name == "mcl_farming:beetroot_0"
	or name == "mcl_farming:pumpkin_stem_0"
	or name == "mcl_farming:melon_stem_0" then
		safe_update(p, "bme_p2:nong_trai_nho", 1)
	end

	-- PRESSURE PLATE → Tech: Kỹ sư sơ cấp
	-- Tất cả loại pressure plate (gỗ, đá, vàng, sắt...)
	if name:find("mesecons_pressureplates:")
	or name:find("mcl_pressureplates:")
	or name == "mcl_core:wooden_pressure_plate_off"
	or name == "mcl_core:stone_pressure_plate_off" then
		add_place(p, "pressure_plate")
		if get_place(p, "pressure_plate") >= 1 then
			safe_update(p, "bme_tech:ky_su_so_cap", 1)
		end
	end

	-- HOPPER → Tech: Băng chuyền (cần đặt 2 hopper)
	if name == "mcl_hoppers:hopper"
	or name == "mcl_hoppers:hopper_side" then
		add_place(p, "hopper")
		if get_place(p, "hopper") >= 2 then
			safe_update(p, "bme_tech:bang_chuyen", 1)
		end
	end

	-- ENCHANTING TABLE → Magic: Nhà thông thái
	if name == "mcl_enchanting:table" then
		safe_update(p, "bme_magic:nha_thong_thai", 1)
	end

	-- BEACON → Secret: Ngọn hải đăng
	if name == "mcl_beacons:beacon" then
		safe_update(p, "bme_secret:ngon_hai_dang", 1)
	end

	-- ENDER PORTAL FRAME (kích hoạt cổng) → Explore: Pháo đài cổ
	if name == "mcl_end:end_portal_frame_eye"
	or name == "mcl_portals:end_portal_frame_eye" then
		safe_update(p, "bme_explore:phao_dai_co", 1)
	end
end)


-- ── CRAFT ─────────────────────────────────────────────────────
core.register_on_craft(function(itemstack, player, old_craft_grid, craft_inv)
	if not player or not player:is_player() then return end
	local p    = player:get_player_name()
	local name = itemstack:get_name()
	local n    = itemstack:get_count()

	-- Cuốc gỗ → GĐ1
	if name == "mcl_tools:pick_wood" then
		safe_update(p, "bme_p1:cong_cu_dau_tien", 1)
	end

	-- Cuốc đá → GĐ2
	if name == "mcl_tools:pick_stone" then
		safe_update(p, "bme_p2:tho_ren_so_cap", 1)
	end

	-- Cuốc sắt → GĐ3
	if name == "mcl_tools:pick_iron" then
		safe_update(p, "bme_p3:tho_mo_chuyen_nghiep", 1)
	end

	-- Giáp sắt (từng mảnh, max=4) → GĐ3: Bảo hộ
	if name == "mcl_armor:helmet_iron"
	or name == "mcl_armor:chestplate_iron"
	or name == "mcl_armor:leggings_iron"
	or name == "mcl_armor:boots_iron" then
		add_craft(p, "iron_armor", 1)
		safe_update(p, "bme_p3:bao_ho", 1)
	end

	-- Iron Ingot từ smelting (output của lò) → GĐ3: Lửa rèn
	if name == "mcl_core:iron_ingot" then
		safe_update(p, "bme_p3:lua_ren", n)
	end

	-- Đồ kim cương → GĐ4: Vua trang bị
	if (name:find("mcl_tools:") or name:find("mcl_armor:")
	or name:find("mcl_weapons:")) and name:find("diamond") then
		safe_update(p, "bme_p4:vua_trang_bi", 1)
	end

	-- Ender Eye → GĐ5: Mắt thần
	if name == "mcl_end:ender_eye" then
		safe_update(p, "bme_p5:mat_than", n)
	end

	-- Thuốc → Magic: Dược sĩ
	if name:find("mcl_potions:potion_") then
		safe_update(p, "bme_magic:duoc_si", 1)
	end

	-- Đồ được phù phép → Magic: Vũ khí huyền thoại
	if name:find("_enchanted") or name:find("mcl_enchanting:") then
		safe_update(p, "bme_magic:vu_khi_huyen_thoai", 1)
	end
end)


-- ── GIẾT SINH VẬT (tích hợp mcl_mobs nếu có) ────────────────
if core.global_exists("mcl_mobs") and mcl_mobs.register_on_mob_death then
	mcl_mobs.register_on_mob_death(function(mob, killer)
		if not killer or not killer:is_player() then return end
		local p   = killer:get_player_name()
		local ent = mob:get_luaentity()
		local mob_name = ent and ent.name or ""

		-- Quái vật thù địch → GĐ4: Thợ săn quái vật
		if HOSTILE_SET[mob_name] then
			safe_update(p, "bme_p4:tho_san_quai_vat", 1)
		end

		-- Raid mobs → Trade: Người bảo vệ
		-- Đếm tích lũy: 20 mob raid = 1 lần hoàn thành quest
		if RAID_SET[mob_name] then
			add_kill(p)
			if get_kills(p) >= 20 then
				safe_update(p, "bme_trade:nguoi_bao_ve", 1)
				kill_trackers[p] = 0
				core.chat_send_player(p,
					"§6[BME]§r Raid đã bị đẩy lùi! Quest Người Bảo Vệ hoàn thành.")
			else
				core.chat_send_player(p,
					"§7[Raid]§r Đã tiêu diệt §e" .. get_kills(p)
					.. "/20§r mob raid.")
			end
		end

		-- Ender Dragon → GĐ5: Huyền thoại
		if mob_name == "mobs_mc:ender_dragon"
		or mob_name == "mcl_end:ender_dragon"
		or mob_name:find("ender_dragon") then
			safe_update(p, "bme_p5:huyen_thoai", 1)
		end

		-- Động vật → GĐ1: Kẻ săn mồi
		if ANIMAL_SET[mob_name] then
			safe_update(p, "bme_p1:ke_san_moi", 1)
		end
	end)
end


-- ── GLOBALSTEP: Detect dimension & trạng thái đặc biệt ───────
local step_timer = 0
core.register_globalstep(function(dtime)
	step_timer = step_timer + dtime
	if step_timer < 1 then return end  -- kiểm tra mỗi 1 giây
	step_timer = 0

	for _, player in ipairs(core.get_connected_players()) do
		local p   = player:get_player_name()
		local pos = player:get_pos()

		-- End dimension (MineClone 5: y >= 4096)
		if pos.y >= 4096 then
			safe_update(p, "bme_p5:hanh_trinh_cuoi", 1)
		end

		-- Đang bay bằng Elytra → Secret: Chinh phục bầu trời
		local inv   = player:get_inventory()
		local chest = inv:get_stack("armor", 2)  -- slot áo giáp
		local vel   = player:get_velocity()
		if chest:get_name() == "mcl_end:elytra"
		and (math.abs(vel.x) > 2 or math.abs(vel.z) > 2) then
			safe_update(p, "bme_secret:ke_chinh_phuc_bau_troi", 1)
		end
	end
end)


-- ============================================================
--  LỆNH CHAT
-- ============================================================

-- Bắt đầu toàn bộ chương trình
core.register_chatcommand("bme_start", {
	description = "Bắt đầu chương trình phục hồi BME",
	func = function(name)
		quests.start_quest(name, "bme_p1:ben_re")
		return true,
			"§6[BME]§r Chương trình phục hồi đã kích hoạt!\n"
			.. "§e→§r Nhiệm vụ đầu tiên: Thu thập 10 khối gỗ."
	end
})

-- Bắt đầu từ giai đoạn bất kỳ (dùng cho bệnh nhân đã có kinh nghiệm)
core.register_chatcommand("bme_goto", {
	description = "(Bác sĩ) Nhảy tới quest cụ thể: /bme_goto <quest_id>",
	privs = { server = true },
	func = function(name, param)
		local qid = param:match("^(%S+)$")
		if not qid then
			return false, "Dùng: /bme_goto <quest_id>"
		end
		quests.start_quest(name, qid)
		return true, "§6[BME]§r Đã nhảy tới quest: " .. qid
	end
})

-- Bác sĩ xác nhận thủ công (khi hook không có: giao dịch, vào End...)
core.register_chatcommand("bme_confirm", {
	description = "(Bác sĩ) Xác nhận tiến độ thủ công: /bme_confirm <player> <quest_id> [số]",
	privs = { server = true },
	func = function(name, param)
		local target, qid, n_str =
			param:match("^(%S+)%s+(%S+)%s*(%d*)")
		if not target or not qid then
			return false, "Dùng: /bme_confirm <player> <quest_id> [số_lượng]"
		end
		local n = tonumber(n_str) or 1
		quests.update_quest(target, qid, n)
		core.chat_send_player(target,
			"§6[BME]§r Bác sĩ xác nhận: §e+" .. n
			.. "§r cho §b" .. qid)
		return true, "Đã cộng " .. n .. " → " .. qid .. " cho " .. target
	end
})

-- Xem tiến độ toàn bộ theo giai đoạn (bảng tiến trình)
core.register_chatcommand("bme_progress", {
	description = "Xem tiến độ phục hồi: /bme_progress [player]",
	func = function(name, param)
		local target = (param ~= "" and param) or name
		local sq = quests.successfull_quests[target] or {}

		local phases = {
			{ p = "bme_p1:", label = "GĐ1 Đồ Gỗ",      n = 4 },
			{ p = "bme_p2:", label = "GĐ2 Đồ Đá",       n = 4 },
			{ p = "bme_p3:", label = "GĐ3 Sắt",          n = 4 },
			{ p = "bme_p4:", label = "GĐ4 Khám phá",     n = 4 },
			{ p = "bme_p5:", label = "GĐ5 End Game",      n = 3 },
			{ p = "bme_tech:",   label = "Nhánh Kỹ thuật",  n = 3 },
			{ p = "bme_magic:",  label = "Nhánh Phù phép",  n = 3 },
			{ p = "bme_trade:",  label = "Nhánh Thương mại",n = 3 },
			{ p = "bme_explore:",label = "Nhánh Khám phá",  n = 4 },
			{ p = "bme_secret:", label = "Nhánh Bí ẩn",     n = 2 },
		}

		core.chat_send_player(name,
			"§6══ BME Tiến Độ: §e" .. target .. " §6══")
		for _, ph in ipairs(phases) do
			local done = 0
			for qid in pairs(sq) do
				if qid:sub(1, #ph.p) == ph.p then
					done = done + 1
				end
			end
			local bar = ""
			for i = 1, ph.n do
				bar = bar .. (i <= done and "§a█" or "§8░")
			end
			core.chat_send_player(name,
				bar .. " §r" .. ph.label
				.. " §7(" .. done .. "/" .. ph.n .. ")")
		end
		return true
	end
})

-- Lệnh debug: xem node name đang nhìn vào (dùng khi quest không nhận)
core.register_chatcommand("bme_debug", {
	description = "Debug: xem tên node đang nhìn vào / đứng trên",
	func = function(name)
		local player = core.get_player_by_name(name)
		if not player then return false, "Không tìm thấy player" end

		-- Node dưới chân
		local pos   = player:get_pos()
		local below = core.get_node({ x = pos.x, y = pos.y - 1, z = pos.z })

		-- Node đang nhìn vào (pointed)
		local dir      = player:get_look_dir()
		local look_pos = {
			x = pos.x + dir.x * 4,
			y = pos.y + dir.y * 4 + 1.5,  -- eye level
			z = pos.z + dir.z * 4,
		}
		local look_node = core.get_node(look_pos)

		core.chat_send_player(name, "§6[BME Debug]§r")
		core.chat_send_player(name,
			"§eNode dưới chân:§r §b" .. below.name)
		core.chat_send_player(name,
			"§eNode đang nhìn:§r §b" .. look_node.name)
		core.chat_send_player(name,
			"§eVị trí (y):§r §b" .. math.floor(pos.y))
		core.chat_send_player(name,
			"§7Gõ /bme_debug để kiểm tra khi quest không nhận node.")
		return true
	end
})

-- Reset toàn bộ tiến trình một player
core.register_chatcommand("bme_reset", {
	description = "(Bác sĩ) Reset tiến trình BME: /bme_reset [player]",
	privs = { server = true },
	func = function(name, param)
		local target = (param ~= "" and param) or name
		quests.active_quests[target]      = {}
		quests.successfull_quests[target] = {}
		quests.failed_quests[target]      = {}
		craft_trackers[target]  = {}
		kill_trackers[target]   = 0
		place_trackers[target]  = {}
		core.chat_send_player(target,
			"§6[BME]§r Tiến trình đã reset — sẵn sàng phiên mới!")
		return true, "Đã reset BME cho " .. target
	end
})