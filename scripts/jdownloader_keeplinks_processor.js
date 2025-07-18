// JDownloader Event Scripter Script for Keeplinks Processing
// This script should be added to JDownloader's Event Scripter
// It will automatically process Keeplinks packages and keep only the highest priority host

// ============================================
// CONFIGURATION
// ============================================

// Define the priority order of hosts (highest priority first)
var HOST_PRIORITY = [
    'rapidgator.net',
    'katfile.com',
    'nitroflare.com',
    'ddownload.com',
    'mega.nz',
    'xup.in',
    'f2h.io',
    'filepv.com',
    'filespayouts.com',
    'uploady.io',
    'keeplinks.org'  // Keeplinks as fallback
];

// Set to true to enable debug logging
var DEBUG = true;

// ============================================
// HELPER FUNCTIONS
// ============================================

/**
 * Log a debug message if debug mode is enabled
 */
function logDebug(message) {
    if (DEBUG) {
        log('DEBUG: ' + message);
    }
}

/**
 * Get the priority of a host (lower number = higher priority)
 * Returns Infinity if host is not in the priority list
 */
function getHostPriority(host) {
    if (!host) return Infinity;
    
    // Convert to lowercase for case-insensitive comparison
    host = host.toLowerCase();
    
    // Check if the host contains any of the priority hosts
    for (var i = 0; i < HOST_PRIORITY.length; i++) {
        if (host.includes(HOST_PRIORITY[i])) {
            return i;
        }
    }
    
    return Infinity;
}

/**
 * Extract the host from a URL
 */
function extractHost(url) {
    if (!url) return '';
    
    try {
        // Remove protocol
        var host = url.replace(/^https?:\/\//, '');
        
        // Remove path and query parameters
        host = host.split('/')[0];
        
        // Remove port number if present
        host = host.split(':')[0];
        
        return host;
    } catch (e) {
        logDebug('Error extracting host from URL: ' + e);
        return '';
    }
}

// ============================================
// MAIN SCRIPT
// ============================================

// This is the main function that JDownloader will call when the event is triggered
function processPackages() {
    logDebug('Starting Keeplinks package processing...');
    
    // Get all packages in LinkGrabber
    var packages = linkgrabber.getPackages();
    
    if (packages.length === 0) {
        logDebug('No packages found in LinkGrabber');
        return;
    }
    
    logDebug('Found ' + packages.length + ' packages to process');
    
    // Process each package
    for (var i = 0; i < packages.length; i++) {
        var pkg = packages[i];
        var links = pkg.getDownloadLinks();
        
        logDebug('Processing package: ' + pkg.getName() + ' (' + links.length + ' links)');
        
        // Group links by host priority
        var linksByHost = {};
        
        // First pass: group links by host and find the best host
        for (var j = 0; j < links.length; j++) {
            var link = links[j];
            var host = extractHost(link.getContentURL() || link.getPluginURL() || '');
            var priority = getHostPriority(host);
            
            if (priority === Infinity) {
                logDebug('Skipping link with unknown host: ' + host);
                continue;
            }
            
            if (!linksByHost[priority]) {
                linksByHost[priority] = [];
            }
            
            linksByHost[priority].push({
                link: link,
                host: host
            });
        }
        
        // Get the best available host (lowest priority number)
        var bestPriority = Math.min.apply(null, Object.keys(linksByHost).map(Number));
        
        if (bestPriority === Infinity) {
            logDebug('No supported hosts found in package: ' + pkg.getName());
            continue;
        }
        
        var bestHostLinks = linksByHost[bestPriority];
        var bestHost = bestHostLinks[0].host;
        
        logDebug('Best host for package "' + pkg.getName() + '": ' + bestHost + ' (priority: ' + bestPriority + ')' + 
                ' - Found ' + bestHostLinks.length + ' links');
        
        // Remove all links except those from the best host
        var linksToKeep = bestHostLinks.map(function(item) { return item.link; });
        var linksToRemove = [];
        
        for (var j = 0; j < links.length; j++) {
            if (linksToKeep.indexOf(links[j]) === -1) {
                linksToRemove.push(links[j]);
            }
        }
        
        // Remove the unwanted links
        if (linksToRemove.length > 0) {
            logDebug('Removing ' + linksToRemove.length + ' links from package "' + pkg.getName() + '"');
            linkgrabber.removeLinks(linksToRemove);
        } else {
            logDebug('No links to remove from package "' + pkg.getName() + '"');
        }
    }
    
    logDebug('Keeplinks package processing completed');
}

// Run the script
processPackages();
