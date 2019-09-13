#!/usr/env python2

import os
import enzyme
import argparse
import re
import shutil
import subprocess
import logging
import time


DRY_RUN = False
DEBUG = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MOVIES_DIR = r"V:\My Videos\Movies"
TV_DIR = r"V:\My Videos\TV"
if DEBUG:
    MOVIES_DIR = r".\test"
    TV_DIR = r".\test"


def fix_makemkv_name(name):
    name, ext = os.path.splitext(name)
    name = name.replace("_", " ").title()
    name = re.search(r'(?i)^(.*?)( t\d+)?$', name).group(1)

    return name + ext


def check_mkv(path):
    mkv = None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            mkv = enzyme.MKV(f)
    except (IOError, OverflowError, enzyme.exceptions.MalformedMKVError, AttributeError) as e:
        print os.path.basename(path), str(e)
    if mkv is None:
        return None
    newname = fix_makemkv_name(os.path.basename(path))
    audio_info = []
    for track in mkv.audio_tracks:
        audio_info.append('%s %s' % (track.language, track.name))
    subtitle_info = []
    for track in mkv.subtitle_tracks:
        subtitle_info.append('%s %s%s%s' % (track.language,
                                            "E" if track.enabled else "",
                                            "D" if track.default else "",
                                            "F" if track.forced else ""))
    track = mkv.video_tracks[0]
    print "%s - %s - %ux%u%s %s - %s - %s" % (
        newname, mkv.info.duration,
        track.width, track.height, 'i' if track.interlaced else '', track.codec_id,
        ', '.join(audio_info), ", ".join(subtitle_info))
    return mkv


def run_handbrake(path, mkv, dest):
    # --start-at-preview <num>
    # --mixdown 5point1,stereo,dpl2 (comma separated for multiple tracks)
    # --subtitle-burned
    cmd = '"{}"'.format(os.path.join(SCRIPT_DIR, "HandbrakeCLI.exe"))
    if mkv.video_tracks[0].height >= 1080:
        preset = "H.264 MKV 1080p30"
        quality = 20
    elif mkv.video_tracks[0].height >= 720:
        preset = "H.264 MKV 720p30"
        quality = 18
    elif mkv.video_tracks[0].height >= 576:
        preset = "H.264 MKV 576p25"
        quality = 18
    else:
        preset = "H.264 MKV 480p30"
        quality = 18
    audio_tracks = []
    audio_codecs = []
    audio_mixdown = []
    audio_bitrates = []
    has_master = False
    for idx, track in enumerate(mkv.audio_tracks):  # filter(lambda track: track.language == "eng", mkv.audio_tracks):
        if track.channels >= 6:
            if track.language == "eng":
                if has_master:
                    continue
                has_master = True
            audio_mixdown.append('5point1')
        else:
            audio_mixdown.append('dpl2')
        audio_tracks.append(str(idx + 1))
        audio_codecs.append('av_aac')
        audio_bitrates.append('384')
    subtitles = []
    for idx, track in enumerate(mkv.subtitle_tracks):
        if track.language == 'eng' or track.language is None:
            subtitles.append(str(idx + 1))
    # subtitle_count = len(filter(lambda track: track.language == "eng", mkv.subtitle_tracks))
    cmd += ' -Z "%s"' % preset
    cmd += ' -i "%s"' % path
    cmd += ' -o "%s"' % dest
    cmd += ' --encoder-preset fast'
    # cmd += ' --encoder-tune <film animation>'
    cmd += ' -q %.1f' % quality
    # cmd += ' --cfr'
    # cmd += ' --audio-lang-list und'  # und for all
    # cmd += ' --all-audio'
    cmd += ' --audio ' + ",".join(audio_tracks)
    cmd += ' -E ' + ",".join(audio_codecs)
    cmd += ' -B ' + ",".join(audio_bitrates)
    cmd += ' --mixdown ' + ",".join(audio_mixdown)  # 5point1,stereo,dpl2
    if len(subtitles) > 0:
        # cmd += ' --subtitle-lang-list eng'
        cmd += ' -s ' + (','.join(['scan'] + subtitles))
        cmd += ' -F'
        cmd += ' --subtitle-burned'
    if DEBUG:
        cmd += ' --start-at duration:%u' % (10 * 60)
        cmd += ' --stop-at duration:%u' % (1 * 60)
    logging.info(cmd)
    print cmd
    if not DRY_RUN:
        mkdir(os.path.dirname(dest))
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        logging.info(output)


def mkdir(dir_):
    if not os.path.isdir(dir_):
        logging.debug("Creating dir %s" % dir_)
        try:
            os.mkdir(dir_)
            return True
        except OSError:
            print "Failed to create %s" % os.path.abspath(dir_)
            return False
    else:
        return True


class ConvertMkvApp(object):
    def __init__(self, delete=False, move_dir=None, movies_out_dir=None, tv_out_dir=None):
        self.delete = delete
        self.move_dir = move_dir
        self.movies_out_dir = movies_out_dir
        self.tv_out_dir = tv_out_dir
        self.completed = 0

    def complete_file(self, path):
        if DRY_RUN:
            return
        self.completed += 1
        if self.delete:
            logging.debug("Deleting %s" % path)
            os.unlink(path)
            return
        if self.move_dir:
            if os.path.isabs(self.move_dir):
                move_dir = self.move_dir
            else:
                move_dir = os.path.join(os.path.dirname(path), self.move_dir)
            if not mkdir(move_dir):
                return
            dest = os.path.join(move_dir, os.path.basename(path))
            logging.debug("Moving %s to %s" % (path, dest))
            try:
                shutil.move(path, dest)
            except shutil.Error:
                print "Failed to move %s to %s" % (path, dest)
                return

    def handle_series(self, dir_):
        names = os.listdir(dir_)
        series_name = os.path.basename(dir_)
        seasons = {}
        for name in names:
            match = re.search(r's(?P<season>\d+)(e(?P<episode>\d+)|d(?P<disc>\d+)_t(?P<title>\d+))(x(?P<qty>\d+))?', name)
            if not match:
                continue
            info = match.groupdict()
            season = seasons.setdefault(int(info['season']), {})
            if info['episode'] is not None:
                disc_num = 0
                episode = title_num = int(info['episode'])
            else:
                disc_num = int(info['disc'])
                title_num = int(info['title'])
                episode = 0
            disc = season.setdefault(disc_num, {})
            disc[title_num] = (name, int(info.get('qty', 1) or 1), episode)
        for season in sorted(seasons.keys()):
            episode = 1
            expected_disc_num = 0
            for disc in sorted(seasons[season].keys()):
                expected_disc_num += 1
                if expected_disc_num != disc:
                    print "Missing disc %u" % expected_disc_num
                for title in sorted(seasons[season][disc].keys()):
                    name, qty, epnum = seasons[season][disc][title]
                    if epnum:
                        episode = epnum
                    outname = "%s - s%02ue%02u" % (series_name, season, episode)
                    episode += qty
                    if qty > 1:
                        outname += "-e%02u" % (episode - 1)

                    cleanname = fix_makemkv_name(name)
                    episode_info = ''
                    match = re.search(r'(?i)^%s(.+)s\d+d\d+' % re.escape(series_name), cleanname)
                    if match:
                        episode_info = match.group(1).strip(' -')
                    if episode_info:
                        outname += " - " + episode_info

                    _, ext = os.path.splitext(name)
                    outname += ext

                    path = os.path.join(dir_, name)
                    mkv = check_mkv(path)
                    if not mkv:
                        print name, "not a valid MKV!"
                        continue
                    print name, "->", outname
                    outpath = os.path.join(self.tv_out_dir, series_name, outname)
                    run_handbrake(path, mkv, outpath)
                    self.complete_file(path)

    def handle_tv(self, dir_):
        tv_files = os.listdir(dir_)
        for series in tv_files:
            series = os.path.join(dir_, series)
            if not os.path.isdir(series):
                continue
            self.handle_series(series)

    def handle_movies(self, dir_):
        files = os.listdir(dir_)
        for file_ in files:
            path = os.path.join(dir_, file_)
            mkv = check_mkv(path)
            if mkv:
                run_handbrake(path, mkv, os.path.join(self.movies_out_dir, fix_makemkv_name(os.path.basename(path))))
                self.complete_file(path)

    def run(self, movie_dir, tv_dir):
        completed = -1
        while completed < self.completed:
            completed = self.completed
            self.handle_movies(movie_dir)
            self.handle_tv(tv_dir)

    def poll(self, movie_dir, tv_dir):
        while True:
            self.run(movie_dir, tv_dir)
            time.sleep(60)


def main():
    global DRY_RUN
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", default=".", nargs='?')
    parser.add_argument("--delete", default=False)
    parser.add_argument("--move-dir", default="Completed")
    parser.add_argument("--log", default="convert.log")
    parser.add_argument("--dry-run", action="store_true", default=False)

    args = parser.parse_args()

    DRY_RUN = args.dry_run

    logging.basicConfig(filename=args.log, level=logging.INFO)

    app = ConvertMkvApp(delete=args.delete, move_dir=args.move_dir, tv_out_dir=TV_DIR, movies_out_dir=MOVIES_DIR)
    app.run(args.dir, os.path.join(args.dir, "TV"))


if __name__ == "__main__":
    main()
