# nrc-extractor
Extract data from Nike Run Club (NRC) app local data on iOS and export into TCX format for import into platforms like Strava


## Instructions for use

### Extraction of SQLite files

The NRC app's SQLite data must first be extracted from the device. 

#### Extraction from iPhone
I used [iMazing](https://imazing.com) to read from a local backup of my iPhone. I found the data in the following path:
`/Apps/AppDomain-com.nike.nikeplus-gps/Documents/Activity/DataStore/activity-data-store.sqlite`

#### Extraction from Apple Watch
1. Open the NRC app.
1. Swipe left until the Settings page is displayed.
1. Scroll down until you see the version number at the bottom and tap it 3 times.
1. Tap the 'DB Browser' option
1. Find the run that you wish to extract and tap it.
1. Tap 'Send to Phone'

Your iPhone will then prompt you to save an extracted SQLite file.

### Explore activity store to identify activity ID

Use an SQLite browser such as [DB Browser for SQLite](https://sqlitebrowser.org) to browse the `activities` table. Find the relevant activity by looking for the relevant `startDate` and `endDate`. If, like me when I wrote this app, you're looking for an activity that failed to sync with the NRC server then you can also look for an activity where the `serverID` is null.

Once you have found the target activity make a note of the `uniqueID` as that's what you will use in the next step.

### Extract activity and generate TCX

Execute the following command
```bash
python generate_tcx.py [path_to_your_sqlite_file] [activity_id] [output_file_name.tcx]
```

NB: On some platforms, e.g. MacOS you will need to use the command `python3` instead of `python`.

**Example:**
If your database is named `backup_folder/activity_data-store.db` and you want to export a run which had a unique ID of 563 to a file named `marathon.tcx`, you would run:

```bash
python generate_tcx.py backup_folder/activity_data-store.db 563 marathon.tcx