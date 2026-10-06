# Athlethium API Documentation

This document describes the API endpoints exposed by the Athlethium backend. These endpoints are implemented as Firebase Gen 2 Cloud Functions.

## Base Configuration

- **Infrastructure:** Firebase Cloud Functions (Gen 2)
- **Region:** `europe-west2`
- **Content-Type:** `application/json`

---

## Endpoints

### 1. Generate Training Session
Generates a personalized daily workout for a user based on their fitness profile (CTL/ATL), history, and equipment.

- **URL:** `/generate_training_session`
- **Method:** `POST`
- **Auth Required:** No (Public)

#### Request Body
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `userId` | String | Yes | The unique identifier for the user. |
| `date` | String | No | The start date for generation (`YYYY-MM-DD`). Defaults to today. |
| `days` | Integer | No | Number of days to generate in advance. Defaults to `1`. |

**Example Request (7-day generation):**
```json
{
  "userId": "user123",
  "date": "2026-05-10",
  "days": 7
}
```

#### Response
- **Success (200 OK)**
  ```json
  {
    "message": "Training generation complete",
    "userId": "user123",
    "generated_dates": ["2026-05-10", "2026-05-11", ...],
    "skipped_dates": ["2026-05-12"]
  }
  ```
- **Error (400 Bad Request):** If `userId` is missing or `date` format is invalid.
- **Error (404 Not Found):** If the user profile is not found in Firestore for a specific date.

---

## Firestore Data Structure Requirements

To ensure the backend functions correctly, your Firestore database MUST be structured as follows:

### 1. User Profile (`users/{userId}`)
The backend expects these specific fields to drive the training algorithm:

| Field | Type | Description |
| :--- | :--- | :--- |
| `ctl` | Number | **(Critical)** Current Fitness (Chronic Training Load). |
| `atl` | Number | **(Critical)** Current Fatigue (Acute Training Load). |
| `weekly_hours` | Number | Target training hours per week (e.g., `12.5`). |
| `daily_available_hours` | Number | Default hours available per day if no schedule is set. |
| `sports` | Array<String> | List of sports the user participates in (e.g., `["cycling", "running"]`). |
| `focused_sports` | Array<String> | Primary sports for priority generation (e.g., `["cycling"]`). |
| `equipment` | Array<String> | Available gear (e.g., `["power_meter", "dumbbells", "bodyweight"]`). |
| `history` | Map | **(Critical)** 7-day training history for TSB calculation. |
| `history.{sport}.focus` | Array<Int> | 7-day focus levels (`-1` to `7`). |
| `history.{sport}.hours` | Array<Num> | 7-day actual duration in hours. |
| `intensity_weeks` | Integer | Training phase configuration (Default: `3`). |
| `injury` / `illness` | Integer | Binary flags (`0` or `1`) that trigger safety recovery sessions. |

**Example Firestore Document (`users/harry123`):**
```json
{
  "ctl": 65.2,
  "atl": 58.4,
  "weekly_hours": 10.0,
  "daily_available_hours": 2.0,
  "sports": ["cycling", "strength", "stretching"],
  "focused_sports": ["cycling"],
  "equipment": ["power_meter", "dumbbells", "bodyweight"],
  "intensity_weeks": 3,
  "injury": 0,
  "illness": 0,
  "history": {
    "cycling": {
      "focus": [1, 2, -1, 1, 0, 1, -1],
      "hours": [1.5, 2.0, 0, 1.5, 0.5, 2.0, 0.0]
    }
  }
}
```

### 2. Workouts Collection (`workouts/{workoutId}`)
When generating or matching FIT files, the backend uses these fields:

- `userId`: String (used for filtering).
- `date`: String (Format: `YYYY-MM-DD`).
- `sport`: String (e.g., `cycling`).
- `completed`: Boolean (Crucial for smart-upload matching).
- `createdAt`: Timestamp.

---

### 3. Upload Workout (.fit file)
Manually marks a generated workout as completed. This updates the workout status in Firestore and recalculates the user's fitness metrics (CTL/ATL).

- **URL:** `/complete_manual_workout`
- **Method:** `POST`
- **Auth Required:** No

#### Request Body
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `workoutId` | String | Yes | The unique identifier for the workout session. |
| `actual_time_sec` | Integer | No | The actual duration of the workout in seconds. |
| `rpe` | Integer | No | Rate of Perceived Exertion (1-10 scale). |
| `notes` | String | No | Optional notes or feedback about the session. |

**Example Request:**
```json
{
  "workoutId": "workout987",
  "actual_time_sec": 3600,
  "rpe": 7,
  "notes": "Felt strong today, focus on recovery tomorrow."
}
```

#### Response
- **Success (200 OK)**
  ```json
  {
    "message": "Workout completed manually",
    "data": {
      "completed": true,
      "completedAt": "2026-05-09T14:30:00Z",
      "completion_type": "manual",
      "actual_time": 3600,
      "rpe": 7,
      "notes": "Felt strong today, focus on recovery tomorrow."
    }
  }
  ```
- **Error (400 Bad Request):** If `workoutId` is missing.
- **Error (500 Internal Server Error):** If the workout is not found or profile update fails.

---

### 3. Upload Workout (.fit file)
Uploads a binary FIT file (from Garmin/Wahoo/etc.) to complete a workout. This endpoint is "smart": it attempts to match the file to a planned workout for the same day and sport.

- **URL:** `/upload_workout_fit`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`
- **Auth Required:** No

#### Request Body (Multipart/Form-Data)
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `userId` | String | Yes | The unique identifier for the user. |
| `file` | Binary | Yes | The `.fit` file to upload. |

#### Smart Matching Logic
1.  **Date & Sport Extraction:** Extracts the start time and activity type (sport) directly from the FIT file.
2.  **Matching:** Searches for an uncompleted planned workout for that user, on that specific date, for that sport.
3.  **Completion:** 
    - If a match is found, it updates that planned workout with the actual metrics (TSS, duration, etc.) and marks it complete.
    - If no match is found, it creates a new "Unplanned" workout record for that day and marks it complete.
4.  **Profile Update:** Recalculates the user's CTL and ATL based on the actual TSS and duration in the file.

#### Response
- **Success (200 OK)**
  ```json
  {
    "message": "Workout uploaded and processed successfully",
    "data": {
      "completed": true,
      "completedAt": "2026-05-09T14:30:00Z",
      "completion_type": "fit_file",
      "actual_time": 3600,
      "actual_tss": 65.5,
      "avg_power": 210,
      "sport": "cycling",
      "fit_file_url": "gs://athlethium-bucket/workouts/..."
    }
  }
  ```
- **Error (400 Bad Request):** If `userId` or `file` is missing.
- **Error (500 Internal Server Error):** If parsing fails or database update fails.

---

## Data Models (Brief)

### User Profile (Firestore: `users/{userId}`)
The profile includes `ctl`, `atl`, `weekly_hours`, `equipment`, `focused_sports`, and a 7-day `history` array.

### Workout (Firestore: `workouts/{workoutId}`)
Contains workout details like `sport`, `intensity`, `targetType`, `tss`, `steps`, and `descriptions`.
