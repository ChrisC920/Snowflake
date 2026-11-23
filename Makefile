# Snowflake developer commands. Run `make help` for the list.
# Uses /Applications/Xcode.app even if xcode-select still points at the Command Line Tools.

DEVELOPER_DIR ?= $(shell if [ -d /Applications/Xcode.app ]; then echo /Applications/Xcode.app/Contents/Developer; else xcode-select -p; fi)
export DEVELOPER_DIR

PROJECT    := Snowflake.xcodeproj
SCHEME     := Snowflake
DERIVED    := build/DerivedData
APP_DEBUG  := $(DERIVED)/Build/Products/Debug/Snowflake.app
APP_RELEASE:= $(DERIVED)/Build/Products/Release/Snowflake.app
XCODEBUILD := xcodebuild -project $(PROJECT) -scheme $(SCHEME) -derivedDataPath $(DERIVED)

.PHONY: help bootstrap generate build release test lint format icons run screenshots clean zip

help: ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Install tools (Homebrew) and generate the Xcode project
	brew bundle --file=Brewfile
	$(MAKE) generate

generate: ## Generate Snowflake.xcodeproj from project.yml
	xcodegen generate

build: generate ## Build the app (Debug)
	$(XCODEBUILD) -configuration Debug build

release: generate ## Build the app (Release)
	$(XCODEBUILD) -configuration Release build

test: generate ## Run package tests and build the app
	cd Packages/SnowflakeKit && swift test
	$(XCODEBUILD) -configuration Debug build

lint: ## Check style (SwiftLint + SwiftFormat)
	swiftlint lint --strict --quiet
	swiftformat . --lint

format: ## Auto-format the code
	swiftformat .
	swiftlint lint --fix --quiet

icons: ## Regenerate icon artwork from scripts/make-icon-art.py
	python3 -I scripts/make-icon-art.py
	scripts/render-icons.sh

run: build ## Build and launch the app
	-pkill -x Snowflake
	open $(APP_DEBUG)

screenshots: build ## Capture every UI state in light and dark → build/screenshots
	scripts/screenshots.sh $(STATES)

zip: release ## Package the Release build as build/Snowflake.zip
	ditto -c -k --keepParent $(APP_RELEASE) build/Snowflake.zip
	@echo "Created build/Snowflake.zip"

clean: ## Remove build output and the generated project
	rm -rf build $(PROJECT) Packages/SnowflakeKit/.build
