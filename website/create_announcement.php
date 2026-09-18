<?php
/*
 * IMPORTANT: Place this file OUTSIDE your web root (one directory up from your public_html/www folder)
 * just like your db connection files.
 * 
 * To create an announcement:
 * 1. Edit the $title and $body variables below
 * 2. Run this file from command line: php create_announcement.php
 *    OR access it directly if it's in a protected location
 * 3. The announcement will be created in your web directory's data/announcements/ folder
 */

// === EDIT THESE TO CREATE AN ANNOUNCEMENT ===
$title = "AQ20/AQ40 now open! ";
$body = "Both raids are open and playable solo or small groups!";
// === END EDIT SECTION ===

// Path to your web directory's data folder
// Adjust this path to point to your actual web directory
// For example, if this file is in C:\laragon\ and your site is in C:\laragon\www\wow.nekos.farm\
$web_data_dir = __DIR__ . '\www\data\announcements';

// Create directory if it doesn't exist
if (!is_dir($web_data_dir)) {
    mkdir($web_data_dir, 0755, true);
}

// Create announcement data
$announcement = [
    'title' => $title,
    'body' => $body,
    'timestamp' => time()
];

// Save to file with timestamp as filename
$filename = $web_data_dir . $announcement['timestamp'] . '.json';
file_put_contents($filename, json_encode($announcement, JSON_PRETTY_PRINT));

echo "✓ Announcement created successfully!\n";
echo "File: $filename\n";
echo "Title: $title\n";
echo "\nTo create another announcement, edit this file and run it again.\n";
?>