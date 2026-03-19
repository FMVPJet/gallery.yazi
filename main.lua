-- ~/.config/yazi/plugins/gallery.yazi/main.lua

local TITLE = "Gallery"
local SELECTION_STATE_FILE = (os.getenv("TMPDIR") or "/tmp") .. "/gallery-yazi-selection.txt"
local RESULT_STATE_FILE = (os.getenv("TMPDIR") or "/tmp") .. "/gallery-yazi-selection-result.txt"
local FOCUS_STATE_FILE = (os.getenv("TMPDIR") or "/tmp") .. "/gallery-yazi-focus.txt"
local IMAGE_EXTENSIONS = {
	"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "heic", "avif",
}

local function shell_escape(value)
	return "'" .. tostring(value):gsub("'", "'\"'\"'") .. "'"
end

local function command_succeeded(ok, _, code)
	if type(ok) == "number" then return ok == 0 end
	if code ~= nil then return ok == true and code == 0 end
	return ok == true
end

local function run_command(cmd)
	local ok_run, why, code = os.execute(cmd)
	return command_succeeded(ok_run, why, code)
end

local function write_text_file(path, content)
	local file, err = io.open(path, "w")
	if not file then
		return false, err
	end
	file:write(content)
	file:close()
	return true
end

local function read_text_file(path)
	local file = io.open(path, "r")
	if not file then
		return nil
	end

	local content = file:read("*a")
	file:close()
	return content
end

local function file_exists(path)
	local file = io.open(path, "r")
	if file then
		file:close()
		return true
	end
	return false
end

local function notify(level, content, timeout)
	ya.notify({
		title = TITLE,
		content = content,
		level = level,
		timeout = timeout or 3,
	})
end

local get_cwd = ya.sync(function()
	return tostring(cx.active.current.cwd)
end)

local get_hovered = ya.sync(function()
	local hovered = cx.active.current.hovered
	if not hovered then return "", false end
	return tostring(hovered.url), hovered.cha.is_dir
end)

local get_selected_urls = ya.sync(function()
	local urls = {}
	for _, u in pairs(cx.active.selected) do
		table.insert(urls, tostring(u))
	end
	return urls
end)

local function get_plugin_dir()
	local source = debug.getinfo(1, "S").source
	if source:sub(1, 1) == "@" then
		return source:match("^@(.+)/main%.lua$")
	end
	return nil
end

local function read_lines(path)
	local content = read_text_file(path)
	if not content then
		return {}
	end

	local lines = {}
	for line in content:gmatch("[^\r\n]+") do
		if line ~= "" then
			table.insert(lines, line)
		end
	end
	return lines
end

local function read_first_line(path)
	local lines = read_lines(path)
	return lines[1]
end

local function is_image(path)
	local lower = tostring(path):lower()
	for _, ext in ipairs(IMAGE_EXTENSIONS) do
		if lower:sub(-( #ext + 1)) == "." .. ext then
			return true
		end
	end
	return false
end

local function build_target_context()
	local cwd = get_cwd()
	local hovered_path, hovered_is_dir = get_hovered()
	local target_dir = hovered_is_dir and hovered_path or cwd
	return cwd, hovered_path, hovered_is_dir, target_dir
end

local function apply_selection_to_target(urls, target_dir, cwd, hovered_path, focus_path)
	if not target_dir or target_dir == "" then
		return
	end

	local restore_target = hovered_path ~= "" and hovered_path or cwd

	if target_dir ~= cwd then
		ya.emit("cd", { target_dir })
	end

	ya.emit("toggle_all", { state = "off" })

	for _, url in ipairs(urls) do
		ya.emit("reveal", { url })
		ya.emit("toggle", { state = "on" })
	end

	if target_dir ~= cwd then
		ya.emit("cd", { cwd })
	end

	local final_target = restore_target
	if focus_path and focus_path ~= "" then
		local focus_parent = path_parent(focus_path)
		if focus_parent == cwd then
			final_target = focus_path
		end
	end

	if final_target ~= "" then
		ya.emit("reveal", { final_target })
	end
end

local function path_parent(path)
	return tostring(path):match("^(.*)/[^/]+$") or ""
end

local function directory_has_images(path)
	local pattern = table.concat(IMAGE_EXTENSIONS, "|")
	local cmd = string.format(
		"find %s -maxdepth 1 -type f | grep -Eiv '/\\.[^/]+$' | grep -Eiq '\\.(%s)$'",
		shell_escape(path),
		pattern
	)
	return run_command(cmd)
end

return {
	entry = function(_, job)
		if job.args and job.args[1] == "prepare_selection" then
			local _, _, _, target_dir = build_target_context()
			local selected_urls = get_selected_urls()
			local lines = {}
			for _, url in ipairs(selected_urls) do
				if is_image(url) and path_parent(url) == target_dir then
					table.insert(lines, url)
				end
			end

			local ok = write_text_file(SELECTION_STATE_FILE, table.concat(lines, "\n"))
			if not ok then
				notify("error", "Couldn't prepare the gallery selection state.")
			end
			os.remove(RESULT_STATE_FILE)
			os.remove(FOCUS_STATE_FILE)
			return
		end

		if job.args and job.args[1] == "apply_selection" then
			local cwd, hovered_path, _, target_dir = build_target_context()
			local urls
			local focus_path = read_first_line(FOCUS_STATE_FILE)
			if file_exists(RESULT_STATE_FILE) then
				urls = read_lines(RESULT_STATE_FILE)
			else
				urls = read_lines(SELECTION_STATE_FILE)
			end

			os.remove(SELECTION_STATE_FILE)
			os.remove(RESULT_STATE_FILE)
			os.remove(FOCUS_STATE_FILE)

			if target_dir == "" then
				return
			end

			apply_selection_to_target(urls, target_dir, cwd, hovered_path, focus_path)
			return
		end

		local _, _, _, target_dir = build_target_context()

		if not directory_has_images(target_dir) then
			notify("warn", "No images found in the target folder.")
		end
	end,
}
