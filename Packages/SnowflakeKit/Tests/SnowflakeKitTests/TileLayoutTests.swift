@testable import SnowflakeKit
import Testing

struct TileLayoutTests {
    @Test func emptyHasNoRows() {
        #expect(TileLayout.rows(ids: [], expandedID: nil).isEmpty)
    }

    @Test func evenCountPairsUp() {
        #expect(TileLayout.rows(ids: ["a", "b", "c", "d"], expandedID: nil) == [["a", "b"], ["c", "d"]])
    }

    @Test func oddCountLeavesLastAlone() {
        #expect(TileLayout.rows(ids: ["a", "b", "c"], expandedID: nil) == [["a", "b"], ["c"]])
    }

    @Test func expandedFirstTakesOwnRow() {
        #expect(TileLayout.rows(ids: ["a", "b", "c"], expandedID: "a") == [["a"], ["b", "c"]])
    }

    @Test func expandedMiddleSplitsRows() {
        #expect(TileLayout.rows(ids: ["a", "b", "c", "d"], expandedID: "b") == [["a"], ["b"], ["c", "d"]])
        #expect(TileLayout.rows(ids: ["a", "b", "c"], expandedID: "b") == [["a"], ["b"], ["c"]])
    }

    @Test func expandedLastTakesOwnRow() {
        #expect(TileLayout.rows(ids: ["a", "b", "c"], expandedID: "c") == [["a", "b"], ["c"]])
        #expect(TileLayout.rows(ids: ["a", "b"], expandedID: "b") == [["a"], ["b"]])
    }

    @Test func unknownExpandedIDIsIgnored() {
        #expect(TileLayout.rows(ids: ["a", "b"], expandedID: "z") == [["a", "b"]])
    }
}
