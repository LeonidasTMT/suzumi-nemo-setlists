#!/usr/bin/env python3
"""
Generate setlist_data.json for karaoke video dashboard.

This script reads from the karaoke_extracted SQLite database and generates
a comprehensive JSON file with:
- All available karaoke videos (excludes future streams)
- Song lists per video
- Aggregated song statistics across all videos
- Artist performance metrics
- Summary statistics

Output format matches the reference structure exactly.
"""

import sqlite3
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Configuration
DB_PATH = '/a0/usr/workdir/setlist_pipeline/data/comments.db'
OUTPUT_PATH = '/a0/usr/workdir/setlist_frontend/setlist_data.json'

def generate_setlist_data():
    """Generate setlist_data.json from karaoke extraction database."""
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"Reading from: {DB_PATH}")
    
    # Get all available karaoke videos with setlists (exclude future streams)
    cursor.execute("""
        SELECT 
            k.id,
            k.title,
            k.upload_date,
            e.songs_json,
            e.confidence,
            e.extractor_pattern,
            e.song_count
        FROM karaoke_filtered k
        LEFT JOIN extracted_setlists_v2 e ON k.id = e.video_id
        WHERE (k.live_status != 'is_upcoming' OR k.live_status IS NULL)
        ORDER BY k.upload_date DESC
    """)
    
    videos_data = []
    total_songs = 0
    song_appearances = defaultdict(lambda: {"count": 0, "artists": set(), "videos": []})
    artist_stats = defaultdict(lambda: {
        "total_performances": 0,
        "songs": defaultdict(int),
        "video_count": 0,
        "videos": []
    })
    
    # Process each video
    for row in cursor.fetchall():
        video_id, title, upload_date_raw, songs_json_str, confidence, pattern_used, song_count_db = row
        
        # Format stream_date as "YYYY-MM-DD 00:00 UTC"
        if upload_date_raw:
            try:
                dt = datetime.strptime(upload_date_raw, '%Y%m%d')
                stream_date = dt.strftime('%Y-%m-%d 00:00 UTC')
            except Exception as e:
                print(f"Warning: Could not parse date for {video_id}: {e}")
                stream_date = "Unknown"
        else:
            stream_date = "Unknown"
        
        # Parse songs from JSON
        songs_array = []
        if songs_json_str:
            try:
                songs_data = json.loads(songs_json_str)
                if isinstance(songs_data, list):
                    songs_array = songs_data
                    total_songs += len(songs_array)
                    
                    # Track song appearances and artist stats
                    for song_entry in songs_array:
                        song_title = song_entry.get('song', song_entry.get('title', ''))
                        artist_name = song_entry.get('artist', song_entry.get('artist_name', ''))
                        timestamp = song_entry.get('timestamp', '')
                        
                        if song_title:
                            song_appearances[song_title]["count"] += 1
                            if artist_name:
                                song_appearances[song_title]["artists"].add(artist_name)
                            if video_id not in song_appearances[song_title]["videos"]:
                                song_appearances[song_title]["videos"].append(video_id)
                        
                        # Track artist statistics
                        if artist_name:
                            if video_id not in artist_stats[artist_name]["videos"]:
                                artist_stats[artist_name]["video_count"] += 1
                                artist_stats[artist_name]["videos"].append(video_id)
                            
                            if song_title and artist_name:
                                artist_stats[artist_name]["songs"][song_title] += 1
            except Exception as e:
                print(f"Warning: Could not parse songs for {video_id}: {e}")
        
        # Build video entry
        video_entry = {
            "video_id": video_id,
            "title": title,
            "author": "@yayo_vmax",
            "stream_date": stream_date,
            "song_count": len(songs_array),
            "songs": songs_array,
            "confidence": confidence if confidence else 0.95,
            "pattern_used": pattern_used if pattern_used else "fixed_artist_parsing"
        }
        videos_data.append(video_entry)
    
    # Recalculate artist total_performances (count actual song performances)
    cursor.execute("SELECT video_id, songs_json FROM extracted_setlists_v2")
    for vid, json_str in cursor.fetchall():
        try:
            songs = json.loads(json_str) if json_str else []
            for song_entry in songs:
                artist_name = song_entry.get('artist', song_entry.get('artist_name', ''))
                if artist_name:
                    artist_stats[artist_name]["total_performances"] += 1
        except Exception as e:
            pass
    # Build all_songs array (sorted by frequency)
    all_songs_list = []
    for song_title, data in sorted(song_appearances.items(), key=lambda x: x[1]["count"], reverse=True):
        entry = {
            "song": song_title,
            "count": data["count"],
            "artists": list(data["artists"] - {''}),  # Remove empty artist strings
            "videos": data["videos"]
        }
        all_songs_list.append(entry)
    
    # Build all_artists array (sorted by total performances)
    all_artists_list = []
    for artist_name, data in sorted(artist_stats.items(), key=lambda x: x[1]["total_performances"], reverse=True):
        if artist_name:
            entry = {
                "name": artist_name,
                "total_performances": data["total_performances"],
                "songs": dict(data["songs"]),
                "video_count": len(set(data["videos"])),
                "videos": list(set(data["videos"]))
            }
            all_artists_list.append(entry)
    
    # Generate summary text
    top_artist = all_artists_list[0] if all_artists_list else None
    top_song = all_songs_list[0] if all_songs_list else None
    
    artist_info = f"Top performer: {top_artist['name']} ({top_artist['total_performances']} performances)"
    song_info = f"Most common song: {top_song['song']} ({top_song['count']} times in {len(top_song['videos'])} videos)"
    
    summary = (
        f"Karaoke setlist data for @yayo_vmax channel. "
        f"{len(videos_data)} videos analyzed with {total_songs} total songs extracted from {len(all_artists_list)} unique artists. "
        f"{artist_info}. {song_info}. "
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    
    # Build final structure
    final_data = {
        "stats": {
            "total_videos": len(videos_data),
            "total_songs": total_songs
        },
        "videos": videos_data,
        "all_songs": all_songs_list,
        "all_artists": all_artists_list,
        "summary": summary
    }
    
    # Write to JSON file
    print(f"Generating {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    
    conn.close()
    
    # Print summary
    file_size = Path(OUTPUT_PATH).stat().st_size / (1024 * 1024)
    print(f"\n✅ Generated: {OUTPUT_PATH}")
    print(f"📊 Statistics:")
    print(f"   - Total videos: {len(videos_data)}")
    print(f"   - Total songs: {total_songs}")
    print(f"   - Unique songs: {len(all_songs_list)}")
    print(f"   - Unique artists: {len(all_artists_list)}")
    print(f"   - File size: {file_size:.2f} MB")
    
    return final_data

if __name__ == "__main__":
    generate_setlist_data()
