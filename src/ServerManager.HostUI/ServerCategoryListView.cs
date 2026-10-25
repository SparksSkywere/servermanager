using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

namespace ServerManager.HostUI;

/// <summary>
/// ListView that mirrors the Python Host Treeview: category parents with [+]/[-] expand/collapse,
/// and clickable column headers for A–Z / numeric sort.
/// </summary>
internal sealed class ServerCategoryListView : ListView
{
    private readonly Dictionary<string, bool> _expanded = new(StringComparer.OrdinalIgnoreCase);
    private List<ServerRow> _rows = new();
    private int _sortColumn = 1; // Server Name
    private bool _sortAscending = true;
    private string? _selectedServer;
    private string _lastStructure = "";
    private bool _rebuildDeferred;
    private bool _recoverQueued;
    private Size _lastLayoutSize;
    private int _lastDpi;

    public ServerCategoryListView()
    {
        View = View.Details;
        FullRowSelect = true;
        MultiSelect = false;
        GridLines = false; // system grid lines render white on dark themes
        HideSelection = false;
        HeaderStyle = ColumnHeaderStyle.Clickable;
        OwnerDraw = true;
        BorderStyle = BorderStyle.None;
        // Owner-draw ListView + DoubleBuffered commonly blanks rows after RDP/DPI until hover.
        DoubleBuffered = false;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.ResizeRedraw, true);
        BackColor = UiTheme.ControlBack;
        ForeColor = UiTheme.ControlFore;

        Columns.Add("Categories", 160);
        Columns.Add("Server Name", 200);
        Columns.Add("Status", 90);
        Columns.Add("PID", 70);
        Columns.Add("CPU Usage", 90);
        Columns.Add("Memory Usage", 100);
        Columns.Add("Uptime", 100);
        Columns.Add("Type", 100);

        ColumnClick += OnColumnClick;
        MouseDown += OnMouseDown;
        DrawColumnHeader += OnDrawColumnHeader;
        DrawItem += OnDrawItem;
        DrawSubItem += OnDrawSubItem;
        Resize += (_, _) => LayoutColumns();
        HandleCreated += (_, _) => LayoutColumns();
        DpiChangedAfterParent += (_, _) => QueueRecoverDisplay();
        SystemEvents.DisplaySettingsChanged += OnDisplaySettingsChanged;
        SystemEvents.SessionSwitch += OnSessionSwitch;
        Disposed += (_, _) =>
        {
            SystemEvents.DisplaySettingsChanged -= OnDisplaySettingsChanged;
            SystemEvents.SessionSwitch -= OnSessionSwitch;
        };
        _headerTheme.Hook(this);
        UpdateHeaderSortGlyphs();
    }

    private void OnDisplaySettingsChanged(object? sender, EventArgs e) => QueueRecoverDisplay();

    private void OnSessionSwitch(object? sender, SessionSwitchEventArgs e)
    {
        if (e.Reason is SessionSwitchReason.SessionUnlock
            or SessionSwitchReason.ConsoleConnect
            or SessionSwitchReason.RemoteConnect
            or SessionSwitchReason.SessionLogon)
            QueueRecoverDisplay();
    }

    private void QueueRecoverDisplay()
    {
        if (IsDisposed || _recoverQueued) return;
        _recoverQueued = true;
        void Run()
        {
            _recoverQueued = false;
            RecoverDisplay();
        }
        try
        {
            if (IsHandleCreated && InvokeRequired)
                BeginInvoke(Run);
            else if (IsHandleCreated)
                // Defer past the DPI/RDP message so item metrics are settled.
                BeginInvoke(Run);
            else
                _recoverQueued = false;
        }
        catch
        {
            _recoverQueued = false;
        }
    }

    /// <summary>
    /// RDP resolution/DPI changes leave owner-draw ListView with stale item rects — rows look blank
    /// until hover, then the next refresh paints blank again. Force a full metrics rebuild.
    /// </summary>
    private void RecoverDisplay()
    {
        if (IsDisposed || !IsHandleCreated) return;
        try
        {
            var keep = _selectedServer ?? SelectedServer;
            _lastStructure = "";
            LayoutColumns();
            if (_rows.Count > 0)
            {
                Rebuild();
                if (keep is not null)
                    SelectServer(keep);
            }
            else
            {
                Refresh();
            }
        }
        catch
        {
            try { Invalidate(true); } catch { /* ignore */ }
        }
    }

    /// <summary>
    /// Fill the client width: grow Categories + Server Name; keep metric columns fixed.
    /// Avoids the empty header strip when the window is maximized.
    /// </summary>
    private void LayoutColumns()
    {
        if (!IsHandleCreated || Columns.Count < 8 || ClientSize.Width < 50) return;

        // Preferred widths for Status … Type
        var status = 88;
        var pid = 68;
        var cpu = 88;
        var mem = 100;
        var uptime = 100;
        var type = 96;
        var fixedTotal = status + pid + cpu + mem + uptime + type;

        var scroll = Items.Count > 0 && (DisplayRectangle.Height < Items.Count * Math.Max(Font.Height + 6, 18))
            ? SystemInformation.VerticalScrollBarWidth
            : 0;
        var avail = Math.Max(50, ClientSize.Width - scroll - 2);

        const int minCat = 100;
        const int minName = 120;
        var flex = avail - fixedTotal;

        // Too narrow for preferred fixed widths — scale the whole row to fit.
        if (flex < minCat + minName)
        {
            var scale = avail / (double)(fixedTotal + minCat + minName);
            status = Math.Max(48, (int)(status * scale));
            pid = Math.Max(40, (int)(pid * scale));
            cpu = Math.Max(48, (int)(cpu * scale));
            mem = Math.Max(56, (int)(mem * scale));
            uptime = Math.Max(56, (int)(uptime * scale));
            type = Math.Max(48, (int)(type * scale));
            fixedTotal = status + pid + cpu + mem + uptime + type;
            flex = Math.Max(minCat + minName, avail - fixedTotal);
        }

        // Split flex between Categories and Server Name (never invert Clamp bounds).
        var nameFloor = Math.Min(minName, flex / 2);
        var catMax = Math.Max(1, flex - nameFloor);
        var catMin = Math.Min(minCat, catMax);
        var preferredCat = flex * 38 / 100;
        var cat = preferredCat < catMin ? catMin : preferredCat > catMax ? catMax : preferredCat;
        var name = Math.Max(1, flex - cat);

        Columns[0].Width = cat;
        Columns[1].Width = name;
        Columns[2].Width = status;
        Columns[3].Width = pid;
        Columns[4].Width = cpu;
        Columns[5].Width = mem;
        Columns[6].Width = uptime;
        Columns[7].Width = type;
    }

    private readonly ListViewHeaderThemer _headerTheme = new();

    public event EventHandler? ServerActivated;

    public string? SelectedServer
    {
        get
        {
            if (SelectedItems.Count == 0) return null;
            return SelectedItems[0].Tag as ServerRow is { } row ? row.Name : null;
        }
    }

    public ServerRow? SelectedServerRow
    {
        get
        {
            if (SelectedItems.Count == 0) return null;
            return SelectedItems[0].Tag as ServerRow;
        }
    }

    public IEnumerable<ServerRow> AllServers => _rows;

    public void Bind(IReadOnlyList<ServerRow> servers, string? preferSelected = null)
    {
        _selectedServer = preferSelected ?? SelectedServer;
        _rows = servers.ToList();

        // Only force a full rebuild on real DPI changes. ClientSize jitters (scrollbar)
        // must not wipe the list every auto-refresh — that is the visible "flash".
        var dpi = IsHandleCreated ? DeviceDpi : 96;
        var dpiChanged = _lastDpi != 0 && dpi != _lastDpi;
        _lastDpi = dpi;
        _lastLayoutSize = ClientSize;
        if (dpiChanged)
            _lastStructure = "";

        var structure = BuildStructureKey();
        if (!dpiChanged && structure == _lastStructure && Items.Count > 0)
            UpdateInPlace();
        else
        {
            Rebuild();
            _lastStructure = structure;
        }
    }

    public void ExpandAll()
    {
        foreach (var cat in CategoryNames())
            _expanded[cat] = true;
        Rebuild();
        _lastStructure = BuildStructureKey();
    }

    public void CollapseAll()
    {
        foreach (var cat in CategoryNames())
            _expanded[cat] = false;
        Rebuild();
        _lastStructure = BuildStructureKey();
    }

    public void ApplyThemeColors()
    {
        BackColor = UiTheme.ControlBack;
        ForeColor = UiTheme.ControlFore;
        foreach (ListViewItem item in Items)
            PaintItemColors(item);
        Invalidate(true);
    }

    private IEnumerable<string> CategoryNames()
        => _rows.Select(r => string.IsNullOrWhiteSpace(r.Category) ? "Uncategorized" : r.Category!)
            .Distinct(StringComparer.OrdinalIgnoreCase);

    private void OnColumnClick(object? sender, ColumnClickEventArgs e)
    {
        if (e.Column == _sortColumn)
            _sortAscending = !_sortAscending;
        else
        {
            _sortColumn = e.Column;
            _sortAscending = true;
        }
        UpdateHeaderSortGlyphs();
        Rebuild();
        _lastStructure = BuildStructureKey();
    }

    private void UpdateHeaderSortGlyphs()
    {
        for (var i = 0; i < Columns.Count; i++)
        {
            var text = Columns[i].Text.TrimEnd(' ', '↑', '↓', '▲', '▼');
            text = text.Replace(" ▲", "").Replace(" ▼", "").TrimEnd();
            if (i == _sortColumn)
                text += _sortAscending ? " ▲" : " ▼";
            Columns[i].Text = text;
        }
        Invalidate();
    }

    private void OnMouseDown(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left) return;
        var hit = HitTest(e.Location);
        if (hit.Item?.Tag is CategoryNode)
        {
            if (hit.SubItem is null || hit.Item.SubItems.IndexOf(hit.SubItem) == 0 || e.X < hit.Item.Bounds.Left + 28)
                ToggleCategory(hit.Item);
        }
    }

    private void ToggleCategory(ListViewItem item)
    {
        if (item.Tag is not CategoryNode node) return;
        _expanded[node.Name] = !_expanded.GetValueOrDefault(node.Name, true);
        var keep = SelectedServer;
        Rebuild();
        _lastStructure = BuildStructureKey();
        if (keep is not null)
            SelectServer(keep);
    }

    private void SelectServer(string name)
    {
        foreach (ListViewItem item in Items)
        {
            if (item.Tag is ServerRow row && string.Equals(row.Name, name, StringComparison.OrdinalIgnoreCase))
            {
                item.Selected = true;
                item.EnsureVisible();
                break;
            }
        }
    }

    private string BuildStructureKey()
    {
        var sb = new StringBuilder();
        sb.Append(_sortColumn).Append(_sortAscending ? 'A' : 'D').Append('|');
        foreach (var (cat, servers) in EnumerateVisible())
        {
            var expanded = _expanded.GetValueOrDefault(cat, true);
            sb.Append(cat).Append(expanded ? '+' : '-');
            if (!expanded) { sb.Append(';'); continue; }
            foreach (var s in servers)
                sb.Append(s.Name).Append(',');
            sb.Append(';');
        }
        return sb.ToString();
    }

    private IEnumerable<(string Cat, List<ServerRow> Servers)> EnumerateVisible()
    {
        var groups = _rows
            .GroupBy(r => string.IsNullOrWhiteSpace(r.Category) ? "Uncategorized" : r.Category!, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.ToList(), StringComparer.OrdinalIgnoreCase);

        foreach (var cat in groups.Keys)
        {
            if (!_expanded.ContainsKey(cat))
                _expanded[cat] = true;
        }

        IEnumerable<string> orderedCategories = groups.Keys;
        if (_sortColumn == 0)
        {
            orderedCategories = _sortAscending
                ? orderedCategories.OrderBy(c => c, StringComparer.OrdinalIgnoreCase)
                : orderedCategories.OrderByDescending(c => c, StringComparer.OrdinalIgnoreCase);
        }
        else
            orderedCategories = orderedCategories.OrderBy(c => c, StringComparer.OrdinalIgnoreCase);

        foreach (var cat in orderedCategories)
            yield return (cat, SortServers(groups[cat]).ToList());
    }

    private void UpdateInPlace()
    {
        _rebuildDeferred = false;
        var dirtyFrom = -1;
        var dirtyTo = -1;
        // No WM_SETREDRAW / Refresh — those flash the whole grid on every timer tick.
        try
        {
            var index = 0;
            foreach (var (cat, servers) in EnumerateVisible())
            {
                var expanded = _expanded.GetValueOrDefault(cat, true);
                var marker = expanded ? "[−]" : "[+]";
                if (index >= Items.Count) { _rebuildDeferred = true; return; }
                var header = Items[index];
                if (header.Tag is not CategoryNode node || !string.Equals(node.Name, cat, StringComparison.OrdinalIgnoreCase))
                {
                    _rebuildDeferred = true;
                    return;
                }
                var headerText = $"{marker}  {cat}";
                if (!string.Equals(header.Text, headerText, StringComparison.Ordinal))
                {
                    header.Text = headerText;
                    MarkDirty(index, ref dirtyFrom, ref dirtyTo);
                }
                PaintItemColors(header);
                index++;

                if (!expanded) continue;
                foreach (var s in servers)
                {
                    if (index >= Items.Count) { _rebuildDeferred = true; return; }
                    var item = Items[index];
                    if (item.Tag is not ServerRow existing || !string.Equals(existing.Name, s.Name, StringComparison.OrdinalIgnoreCase))
                    {
                        _rebuildDeferred = true;
                        return;
                    }
                    item.Tag = s;
                    if (ApplyServerTexts(item, s))
                        MarkDirty(index, ref dirtyFrom, ref dirtyTo);
                    PaintItemColors(item);
                    if (_selectedServer is not null &&
                        string.Equals(_selectedServer, s.Name, StringComparison.OrdinalIgnoreCase) &&
                        !item.Selected)
                        item.Selected = true;
                    index++;
                }
            }
            if (index != Items.Count)
                _rebuildDeferred = true;
        }
        finally
        {
            if (_rebuildDeferred)
            {
                _rebuildDeferred = false;
                Rebuild();
            }
            else if (dirtyFrom >= 0)
            {
                RedrawItems(dirtyFrom, dirtyTo, true);
            }
        }
    }

    private static void MarkDirty(int index, ref int dirtyFrom, ref int dirtyTo)
    {
        if (dirtyFrom < 0)
        {
            dirtyFrom = dirtyTo = index;
            return;
        }
        if (index < dirtyFrom) dirtyFrom = index;
        if (index > dirtyTo) dirtyTo = index;
    }

    private void Rebuild()
    {
        SetRedraw(false);
        BeginUpdate();
        try
        {
            Items.Clear();
            foreach (var (cat, servers) in EnumerateVisible())
            {
                var expanded = _expanded.GetValueOrDefault(cat, true);
                var marker = expanded ? "[−]" : "[+]";
                var header = new ListViewItem(new[]
                {
                    $"{marker}  {cat}",
                    "", "", "", "", "", "", ""
                })
                {
                    Tag = new CategoryNode(cat),
                    Font = new Font(Font, FontStyle.Bold),
                    UseItemStyleForSubItems = true
                };
                PaintItemColors(header);
                Items.Add(header);

                if (!expanded) continue;

                foreach (var s in servers)
                {
                    var item = new ListViewItem(new[] { "    ", "", "", "", "", "", "", "" })
                    {
                        Tag = s,
                        UseItemStyleForSubItems = true
                    };
                    ApplyServerTexts(item, s);
                    PaintItemColors(item);
                    Items.Add(item);
                    if (_selectedServer is not null &&
                        string.Equals(_selectedServer, s.Name, StringComparison.OrdinalIgnoreCase))
                        item.Selected = true;
                }
            }
        }
        finally
        {
            EndUpdate();
            SetRedraw(true);
            LayoutColumns();
            Refresh();
        }
        _lastStructure = BuildStructureKey();
    }

    private static bool ApplyServerTexts(ListViewItem item, ServerRow s)
    {
        var running = string.Equals(s.Status, "running", StringComparison.OrdinalIgnoreCase);
        EnsureSubItemCount(item, 8);
        var changed = false;
        changed |= SetSubText(item, 0, "    ");
        changed |= SetSubText(item, 1, s.Name);
        changed |= SetSubText(item, 2, s.Status);
        changed |= SetSubText(item, 3, running ? (s.Pid?.ToString() ?? "") : "");
        changed |= SetSubText(item, 4, running ? FormatCpu(s) : "");
        changed |= SetSubText(item, 5, running ? FormatMemory(s) : "");
        changed |= SetSubText(item, 6, running ? (s.Uptime ?? "") : "—");
        changed |= SetSubText(item, 7, s.Type);
        return changed;
    }

    private static bool SetSubText(ListViewItem item, int index, string text)
    {
        if (string.Equals(item.SubItems[index].Text, text, StringComparison.Ordinal))
            return false;
        item.SubItems[index].Text = text;
        return true;
    }

    private static void EnsureSubItemCount(ListViewItem item, int count)
    {
        while (item.SubItems.Count < count)
            item.SubItems.Add("");
    }

    private static void PaintItemColors(ListViewItem item)
    {
        Color back;
        Color fore;
        if (item.Tag is CategoryNode)
        {
            back = UiTheme.CategoryBack;
            fore = UiTheme.CategoryFore;
        }
        else if (item.Tag is ServerRow s)
        {
            var running = string.Equals(s.Status, "running", StringComparison.OrdinalIgnoreCase);
            back = UiTheme.ControlBack;
            fore = running ? UiTheme.RunningFore : UiTheme.StoppedFore;
        }
        else
        {
            back = UiTheme.ControlBack;
            fore = UiTheme.ControlFore;
        }
        if (item.BackColor.ToArgb() != back.ToArgb())
            item.BackColor = back;
        if (item.ForeColor.ToArgb() != fore.ToArgb())
            item.ForeColor = fore;
    }

    private IEnumerable<ServerRow> SortServers(IEnumerable<ServerRow> servers)
    {
        IOrderedEnumerable<ServerRow> ordered = _sortColumn switch
        {
            0 => servers.OrderBy(s => s.Category ?? "Uncategorized", StringComparer.OrdinalIgnoreCase),
            2 => servers.OrderBy(s => s.Status, StringComparer.OrdinalIgnoreCase),
            3 => servers.OrderBy(s => s.Pid ?? int.MinValue),
            4 => servers.OrderBy(s => s.Cpu ?? double.MinValue),
            5 => servers.OrderBy(s => s.MemoryMb ?? double.MinValue),
            6 => servers.OrderBy(s => s.Uptime ?? "", StringComparer.OrdinalIgnoreCase),
            7 => servers.OrderBy(s => s.Type, StringComparer.OrdinalIgnoreCase),
            _ => servers.OrderBy(s => s.Name, StringComparer.OrdinalIgnoreCase)
        };
        return _sortAscending ? ordered : ordered.Reverse();
    }

    private static string FormatCpu(ServerRow s)
        => s.Cpu is null ? "" : $"{s.Cpu.Value:0.0}%";

    private static string FormatMemory(ServerRow s)
        => s.MemoryMb is null ? "" : $"{s.MemoryMb.Value:0} MB";

    private void OnDrawColumnHeader(object? sender, DrawListViewColumnHeaderEventArgs e)
    {
        var hot = (e.State & ListViewItemStates.Hot) != 0;
        using var bg = new SolidBrush(hot ? UiTheme.HoverBack : UiTheme.HeaderBack);
        e.Graphics.FillRectangle(bg, e.Bounds);
        using var border = new Pen(UiTheme.Border);
        e.Graphics.DrawLine(border, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
        e.Graphics.DrawLine(border, e.Bounds.Right - 1, e.Bounds.Top, e.Bounds.Right - 1, e.Bounds.Bottom);
        TextRenderer.DrawText(
            e.Graphics,
            e.Header?.Text ?? "",
            Font,
            Rectangle.Inflate(e.Bounds, -4, 0),
            UiTheme.HeaderFore,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }

    private void OnDrawItem(object? sender, DrawListViewItemEventArgs e)
    {
        // Must paint the row background ourselves; DrawDefault=false with empty work
        // leaves blank rows when subitem bounds are stale after RDP/DPI.
        e.DrawDefault = false;
        if (e.Item is null) return;

        var bounds = NormalizeItemBounds(e.Item, e.Bounds);
        if (bounds.Width <= 0 || bounds.Height <= 0) return;

        var selected = e.Item.Selected;
        var hot = !selected && (e.State & ListViewItemStates.Hot) != 0;
        Color back;
        if (selected)
            back = UiTheme.HighlightBack;
        else if (hot)
            back = UiTheme.HoverBack;
        else
            back = e.Item.BackColor.IsEmpty ? UiTheme.ControlBack : e.Item.BackColor;

        using var brush = new SolidBrush(back);
        e.Graphics.FillRectangle(brush, bounds);
    }

    private void OnDrawSubItem(object? sender, DrawListViewSubItemEventArgs e)
    {
        if (e.Item is null || e.SubItem is null) return;
        e.DrawDefault = false;

        var bounds = NormalizeSubItemBounds(e);
        if (bounds.Width <= 0 || bounds.Height <= 0) return;

        var selected = e.Item.Selected;
        var hot = !selected && (e.ItemState & ListViewItemStates.Hot) != 0;

        Color back;
        Color fore;
        if (selected)
        {
            back = UiTheme.HighlightBack;
            fore = UiTheme.HighlightFore;
        }
        else if (hot)
        {
            back = UiTheme.HoverBack;
            fore = ResolveItemFore(e.Item);
        }
        else
        {
            back = e.Item.BackColor.IsEmpty ? UiTheme.ControlBack : e.Item.BackColor;
            fore = ResolveItemFore(e.Item);
        }

        using (var brush = new SolidBrush(back))
            e.Graphics.FillRectangle(brush, bounds);

        if (e.ColumnIndex == 0)
        {
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(pen, bounds.Right - 1, bounds.Top, bounds.Right - 1, bounds.Bottom);
        }
        using (var grid = new Pen(UiTheme.Border))
            e.Graphics.DrawLine(grid, bounds.Left, bounds.Bottom - 1, bounds.Right, bounds.Bottom - 1);

        var font = e.Item.Font ?? Font;
        TextRenderer.DrawText(
            e.Graphics,
            e.SubItem.Text ?? "",
            font,
            Rectangle.Inflate(bounds, -4, 0),
            fore,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
    }

    private static Rectangle NormalizeItemBounds(ListViewItem item, Rectangle reported)
    {
        if (reported.Width > 0 && reported.Height > 0)
            return reported;
        try { return item.GetBounds(ItemBoundsPortion.Entire); }
        catch { return reported; }
    }

    private static Rectangle NormalizeSubItemBounds(DrawListViewSubItemEventArgs e)
    {
        var reported = e.Bounds;
        if (reported.Width > 0 && reported.Height > 0)
            return reported;
        try
        {
            if (e.Item is null) return reported;
            if (e.ColumnIndex <= 0)
                return e.Item.GetBounds(ItemBoundsPortion.Label);
            if (e.ColumnIndex < e.Item.SubItems.Count)
            {
                var b = e.Item.SubItems[e.ColumnIndex].Bounds;
                if (b.Width > 0 && b.Height > 0)
                    return b;
            }
            return e.Item.GetBounds(ItemBoundsPortion.Entire);
        }
        catch
        {
            return reported;
        }
    }

    private static Color ResolveItemFore(ListViewItem item)
    {
        if (!item.ForeColor.IsEmpty)
            return item.ForeColor;
        return UiTheme.ControlFore;
    }

    private void SetRedraw(bool enable)
    {
        if (!IsHandleCreated) return;
        SendMessage(Handle, WmSetRedraw, enable ? 1 : 0, 0);
    }

    private const int WmSetRedraw = 0x000B;

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);

    private sealed record CategoryNode(string Name);

    protected override void OnDoubleClick(EventArgs e)
    {
        if (SelectedServerRow is not null)
            ServerActivated?.Invoke(this, EventArgs.Empty);
        else
            base.OnDoubleClick(e);
    }
}
