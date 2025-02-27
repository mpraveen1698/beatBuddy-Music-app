from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity, create_access_token
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.utils import secure_filename
import os
from flask_cors import CORS
import pandas as pd
from sqlalchemy.sql import func
from tqdm import tqdm
from sqlalchemy.exc import SQLAlchemyError
import pandas as pd
import random
import logging
from search_via_music.fingerprint_generator import read_audio, fingerprint

from itertools import groupby
from operator import itemgetter
import pandas as pd
from time import time
# from search_via_text.colbert import search_documents
from itertools import groupby
from pydub import AudioSegment
# Load CSV file into a DataFrame
# Setting up the database path
current_directory = os.getcwd()
instance_directory = os.path.join(current_directory, "instance")
db_name = "beatbuddy.db"
db_path = os.path.join(instance_directory, db_name)
db_uri = 'sqlite:///' + db_path.replace("\\", "/")
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'webm', 'mp3', 'wav'}
# Ensure the instance directory exists
if not os.path.exists(instance_directory):
    os.makedirs(instance_directory)

app = Flask(__name__)
CORS(app, origins=['*'])
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # To avoid overhead and deprecation warning
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'mp3', 'wav'}

logging.basicConfig(level=logging.INFO) 

# Setup database
db = SQLAlchemy(app)
jwt = JWTManager(app)


# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)


recc_data = pd.read_excel("recommended_songs_new_songsdb.xlsx", engine = "openpyxl")

# Models
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    ratings = db.relationship('Rating', backref='user', lazy=True)

class Song(db.Model):
    __tablename__ = 'songs'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    album = db.Column(db.String(200), nullable=True)
    youtube_link = db.Column(db.String(200), nullable=True)
    nearest_songs = db.Column(db.String(200), nullable=True)
    ratings = db.relationship('Rating', backref='song', lazy=True)
    fingerprints = db.relationship('Fingerprint', backref='song', lazy=True)

class Rating(db.Model):
    __tablename__ = 'ratings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    song_id = db.Column(db.Integer, db.ForeignKey('songs.id'), nullable=False)
    rating = db.Column(db.Float, nullable=False)

class Fingerprint(db.Model):
    __tablename__ = 'fingerprints'
    id = db.Column(db.Integer, primary_key=True)
    song_id = db.Column(db.Integer, db.ForeignKey('songs.id'), nullable=False)
    hash = db.Column(db.String(255), nullable=False)
    offset = db.Column(db.Integer, nullable=False)


# User loader
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes
@app.route('/')
def index():
    return "Beats buddy Python Api"

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    user = User.query.filter_by(username=username, password=password).first()
    if user:
        access_token = create_access_token(identity=username)
        login_user(user)
        return jsonify({"message": "Login successful", "access_token": access_token}), 200
    return jsonify({"message": "Login failed"}), 401  # Unauthorized access

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')  # In production, ensure this is hashed
        email = data.get('email')

        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            return jsonify({'message': 'Username or email already exists'}), 409

        new_user = User(username=username, password=password, email=email)
        db.session.add(new_user)
        db.session.commit()

        return jsonify({'message': 'User created successfully', 'userId': new_user.id}), 201  # Assuming id is auto-generated

    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    print("Uploading audio")
    print("Request received")
    print(request.files)
    # if 'audio' not in request.files:
    #     return jsonify({'error': 'No audio file part'}), 400
    
    audio = request.files['file']
    print("1")
    if audio.filename == '':
        return jsonify({'error': 'No selected audio file'}), 400
    print("2")
    if audio:
        print("3")
        filename = secure_filename(audio.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        audio.save(file_path)
        return jsonify({'message': 'Audio file uploaded successfully', 'path': file_path}), 200
    else:
        return jsonify({'error': 'Invalid file format or extension'}), 400



@app.route('/all_songs', methods=['GET'])
def get_all_songs():

    songs = db.session.query(
        Song.id, Song.title, Song.artist, Song.album, Song.youtube_link,
        func.avg(Rating.rating).label('average_rating')
    ).outerjoin(Rating).group_by(Song.id).limit(10).all()

    songs_data = [{
        'id': song.id,
        'title': song.title,
        'artist': song.artist,
        'album': song.album,
        'youtube_link': song.youtube_link,
        'average_rating': float(song.average_rating) if song.average_rating else None
    } for song in songs]
    return jsonify(songs_data)


def find_matches_in_database(hashes, csv_file_path = "./preprocessing/optimized_audio_fingerprint_database.csv", batch_size=1000):
    # Load the CSV data
    df = pd.read_csv(csv_file_path)
    batch_size = 1000
    # Prepare the mapper from your hashes
    mapper = {}
    for hsh, offset in hashes:
        upper_hash = hsh.upper()
        if upper_hash in mapper:
            mapper[upper_hash].append(offset)
        else:
            mapper[upper_hash] = [offset]
    values = list(mapper.keys())
    
    # Initialize results and deduplication dict
    results = []
    dedup_hashes = {}
    t = time()
    # Iterate through the DataFrame
    for index in range(0, len(hashes), batch_size):
        batch_hashes = values[index:index + batch_size]
        db_matches = df[df['Hash'].str.upper().isin(batch_hashes)]
        
        for _, row in db_matches.iterrows():
            hsh, sid, db_offset = row['Hash'].upper(), row['SongID'], row['Offset']
            if sid not in dedup_hashes.keys():
                dedup_hashes[sid] = 1
            else:
                dedup_hashes[sid] += 1

            for song_sampled_offset in mapper[hsh]:
                results.append((sid, db_offset - song_sampled_offset))

    query_time = time() - t
    print(f"Query time: {query_time}")
    t = time()
    results = align_matches(results, dedup_hashes, len(hashes), df)
    print(f"Alignment time: {time() - t}")
    return results


def align_matches(matches, dedup_hashes, queried_hashes, df_songs, topn=5, default_fs=44100, window_size=4096, overlap_ratio=0.5):
    
    sorted_matches = sorted(matches, key=itemgetter(0, 1))
    counts = [(*key, len(list(group))) for key, group in groupby(sorted_matches, key=itemgetter(0, 1))]
    
    songs_matches = sorted(
        [max(list(group), key=itemgetter(2)) for key, group in groupby(counts, key=itemgetter(0))],
        key=itemgetter(2), reverse=True
    )
    print(songs_matches)
    songs_result = [song_id for song_id, _, _ in songs_matches[:min(len(songs_matches), topn)]]
    return songs_result

@app.route('/search_via_clip', methods=['GET'])
def get_search_clip():
    upload_folder = app.config['UPLOAD_FOLDER']
    files = os.listdir(upload_folder)
    if files:  # Check if any files are present in the folder
        filename = files[0]  # Assuming only one file is present
        if filename.endswith(".mp3") or filename.endswith(".wav"):
            original_path = os.path.join(upload_folder, filename)
            final_path = os.path.join(upload_folder, 'recording.mp3')

            # Open the audio file using a context manager
            with open(original_path, 'rb') as f:
                audio = AudioSegment.from_file(f)
                audio.export(final_path, format='mp3')

            channels, samplerate = read_audio(final_path)

            print(channels, samplerate)
            hashes = set()
            for channel in channels:
                channel_fingerprints = fingerprint(channel, Fs=samplerate)
                hashes.update(channel_fingerprints)
            print("Done generating hashes", len(hashes))
            song_ids = find_matches_in_database(hashes)
            song_ids = [x + 1 for x in song_ids]
            print(song_ids)
            if song_ids:
                songs = db.session.query(
                    Song.id, Song.title, Song.artist, Song.album, Song.youtube_link,
                    func.avg(Rating.rating).label('average_rating')
                ).filter(Song.id.in_(song_ids)).outerjoin(Rating).group_by(Song.id).all()
                songs = sorted(songs,key=lambda song: song_ids.index(song.id))
                songs_data = [{
                    'id': song.id,
                    'title': song.title,
                    'artist': song.artist,
                    'album': song.album,
                    'youtube_link': song.youtube_link,
                    'average_rating': float(song.average_rating) if song.average_rating else None
                } for song in songs]

            # Check if the files exist before removing them
            if os.path.isfile(original_path):
                try:
                    os.remove(original_path)
                except PermissionError:
                    print(f"Failed to remove file: {original_path}")

            if os.path.isfile(final_path):
                try:
                    os.remove(final_path)
                except PermissionError:
                    print(f"Failed to remove file: {final_path}")

            print(songs_data)
    return jsonify(songs_data)


@app.route('/search_via_text', methods=['GET'])
def get_search_text():
    query = request.args.get('query')
    # song_ids=search_documents(query)
    song_ids = [1, 2, 3, 4, 5]
    song_ids = [x + 1 for x in song_ids]

    try:
        songs = db.session.query(
            Song.id, Song.title, Song.artist, Song.album, Song.youtube_link,
            func.avg(Rating.rating).label('average_rating')
        ).filter(Song.id.in_(song_ids)).outerjoin(Rating).group_by(Song.id).all()
        songs = sorted(songs,key=lambda song: song_ids.index(song.id))
        songs_data = [{
            'id': song.id,
            'title': song.title,
            'artist': song.artist,
            'album': song.album,
            'youtube_link': song.youtube_link,
            'average_rating': float(song.average_rating) if song.average_rating else None
        } for song in songs]
        print(songs_data)
    except Exception as e:
        print(e.args)

    return jsonify(songs_data)

@app.route('/rate_song', methods=['POST'])
@jwt_required()
def rate_song():
    user_id = get_jwt_identity()
    song_id = request.json.get('song_id')
    rating_value = request.json.get('rating')

    # Check if the rating already exists
    rating = Rating.query.filter_by(user_id=user_id, song_id=song_id).first()
    if rating:
        rating.rating = rating_value
    else:
        rating = Rating(user_id=user_id, song_id=song_id, rating=rating_value)
        db.session.add(rating)

    db.session.commit()
    return jsonify({'message': 'Rating updated successfully'}), 200


# @app.route('/recommendations', methods=['GET'])
# def get_recommendations():
#     # if request.method == "GET":
#     data = request.get_json()
#     user_id = data.get('userid')
#     if user_id in recc_data['User']:
#         song_ids = recc_data[recc_data['User']==user_id]["Recommended Songs"]
#     else:
#         user_id_rand = random.randint(0, 1999)
#         song_ids = recc_data[recc_data['User']==user_id_rand]["Recommended Songs"]
#     app.logger.info('Song IDS', song_ids)
#     print("######### song_ids",song_ids)
#     try:
#         songs = db.session.query(
#             Song.id, Song.title, Song.artist, Song.album, Song.youtube_link,
#             func.avg(Rating.rating).label('average_rating')
#         ).filter(Song.id.in_(song_ids)).oupoterjoin(Rating).group_by(Song.id).all()
#         songs = sorted(songs,key=lambda song: song_ids.index(song.id))
#         songs_data = [{
#             'id': song.id,
#             'title': song.title,
#             'artist': song.artist,
#             'album': song.album,
#             'youtube_link': song.youtube_link,
#             'average_rating': float(song.average_rating) if song.average_rating else None
#         } for song in songs]
#         print(songs_data)
#     except Exception as e:
#         print(e.args)
#     return jsonify(song_ids)


def load_songs():
    songs_df = pd.read_csv('./preprocessing/SONGS_DB.csv', encoding='utf-8')
    for index, row in tqdm(songs_df.iterrows()):
        song = Song(
            title=row['track_name'],
            artist=row['artists'],
            album=row['album_name'],  # Using .get() to handle missing data gracefully
            youtube_link=row['YouTube URL']
        )
        db.session.add(song)
    db.session.commit()

def load_finger_prints():
    # Load the CSV file into a DataFrame
    print("Loading data...")
    df = pd.read_csv('./preprocessing/optimized_audio_fingerprint_database.csv', encoding='utf-8', usecols=['SongID', 'Hash', 'Offset'])

    # # Filter rows where SongID <= 250
    # print("Filtering data...")
    # filtered_df = Fingerprint_df[Fingerprint_df['SongID'] > 250]

    # Batch size for bulk insert
    batch_size = 10000  # Adjust based on memory and performance considerations
    total_rows = len(df)
    print(f"Total rows to process: {total_rows}")

    try:
        # Process in chunks
        for start in tqdm(range(0, total_rows, batch_size)):
            end = min(start + batch_size, total_rows)
            batch = df.iloc[start:end]
            # Create a list of Fingerprint objects to bulk insert
            fingerprints = [
                Fingerprint(
                    song_id=row['SongID'],
                    hash=row['Hash'],
                    offset=row['Offset']
                ) for index, row in batch.iterrows()
            ]
            # Bulk insert using SQLAlchemy's bulk_save_objects or similar method
            db.session.bulk_save_objects(fingerprints)
            db.session.commit()
            print(f"Processed {end} of {total_rows}")
    except SQLAlchemyError as e:
        print(f"An error occurred: {e}")
        db.session.rollback()

# Main application logic
if __name__ == '__main__':
    # Create or recreate the database
    with app.app_context():
        db.create_all()
        if(Song.query.count() == 0):
            print("Songs table is empty")
            load_songs()
        if(Fingerprint.query.count() == 0):
            print("Finerprints table is empty")
            load_finger_prints()

    app.run(port=5000, debug=True)
