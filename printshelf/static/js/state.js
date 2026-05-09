export const state = {
  items: [],
  selectedItemId: null,
  hasBridge: false,
  bridgeDetected: false,
  scanPollTimer: null,
  scanPollIntervalMs: 0,
  lastLoadedRunId: null,
  currentView: "browse",
  tags: [],
  activeTag: null,
  taggedItems: [],
  checkedTagItemIds: new Set(),
  showCheckedOnly: false,
  tagListRequestId: 0,
  taggedItemsRequestId: 0,
  itemsLoading: false,
  saveInFlight: false,
  scanInFlight: false,
  bulkInFlight: false,
};

export const ACTIVE_SCAN_STATUSES = new Set([
  "counting",
  "running",
  "canceling",
  "paused",
]);
