# JDownloader Keeplinks Processor

This script helps JDownloader automatically process Keeplinks packages by keeping only the highest priority host from each package.

## Features

- Automatically processes Keeplinks packages in JDownloader's LinkGrabber
- Keeps only the highest priority host for each package
- Configurable host priority list
- Debug logging for troubleshooting

## Installation

1. Open JDownloader
2. Go to `Settings` > `Advanced Settings`
3. Search for `Event Scripter`
4. Click on `Add New Script`
5. Give it a name like "Keeplinks Processor"
6. Copy the contents of `jdownloader_keeplinks_processor.js` into the script editor
7. Save the script

## Configuration

You can modify the following variables in the script:

- `HOST_PRIORITY`: Define the priority order of hosts (highest priority first)
- `DEBUG`: Set to `true` to enable debug logging

## How It Works

1. The script runs automatically when triggered by JDownloader's event system
2. It checks all packages in the LinkGrabber
3. For each package, it identifies all unique hosts
4. It keeps only the links from the highest priority host
5. All other links are removed from the package

## Trigger Configuration

For best results, set up the script to run on these events:

1. `A Package Added` - To process new packages as they're added
2. `Interval` - Periodically check for new packages (e.g., every 30 seconds)

## Troubleshooting

If the script isn't working as expected:

1. Enable debug logging by setting `DEBUG = true`
2. Check JDownloader's log for debug messages
3. Verify that the script is enabled and the trigger is set up correctly

## Notes

- The script only processes packages in the LinkGrabber
- It doesn't modify any downloaded files
- Make sure JDownloader is allowed to run scripts in its security settings
