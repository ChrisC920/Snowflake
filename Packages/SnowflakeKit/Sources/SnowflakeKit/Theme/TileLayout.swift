/// Pure layout helpers for the menu bar panel.
public enum TileLayout {
    /// Groups ids into rows of two; the expanded tile takes a row of its own.
    public static func rows(ids: [String], expandedID: String?) -> [[String]] {
        var rows: [[String]] = []
        var pending: [String] = []
        for id in ids {
            if id == expandedID {
                if !pending.isEmpty {
                    rows.append(pending)
                    pending = []
                }
                rows.append([id])
            } else {
                pending.append(id)
                if pending.count == 2 {
                    rows.append(pending)
                    pending = []
                }
            }
        }
        if !pending.isEmpty {
            rows.append(pending)
        }
        return rows
    }
}
