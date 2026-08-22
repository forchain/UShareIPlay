package io.ushareiplay.loopback;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.pm.PackageManager;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioPlaybackCaptureConfiguration;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Bundle;
import android.os.Build;
import android.os.Environment;
import android.widget.TextView;
import android.content.pm.ServiceInfo;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

public final class MainActivity extends Activity {
    private static final int LOOPBACK_SAMPLE_RATE = 8000;
    private static final int PROBE_SAMPLE_RATE = 16000;
    private static final int SOURCE_SECONDS = 5;
    private static final int CAPTURE_SECONDS = 7;
    private static final int SYNTHETIC_SECONDS = 30;
    private static final String MODE_EXTRA = "mode";
    private static final String MODE_LOOPBACK = "loopback";
    private static final String MODE_PROBE = "probe";
    private static final String MODE_SYNTHETIC = "synthetic";
    private static final String MODE_PLAYBACK_CAPTURE = "playback_capture";
    private static final int PROJECTION_REQUEST_CODE = 7001;
    private TextView status;
    private String mode;
    private int delayMs;
    private int captureUid;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        status = new TextView(this);
        mode = getIntent().getStringExtra(MODE_EXTRA);
        if (mode == null) mode = MODE_LOOPBACK;
        delayMs = getIntent().getIntExtra("delay_ms", 0);
        captureUid = getIntent().getIntExtra("capture_uid", -1);
        status.setText("Preparing " + mode);
        setContentView(status);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        } else {
            beginMode();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(requestCode, permissions, grants);
        if (requestCode == 1 && grants.length == 1 && grants[0] == PackageManager.PERMISSION_GRANTED) {
            beginMode();
        } else {
            status.setText("RECORD_AUDIO permission denied");
        }
    }

    private void beginMode() {
        if (MODE_PLAYBACK_CAPTURE.equals(mode)) {
            MediaProjectionManager manager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
            if (manager == null) {
                status.setText("MediaProjection unavailable");
                return;
            }
            startActivityForResult(manager.createScreenCaptureIntent(), PROJECTION_REQUEST_CODE);
        } else {
            startCapture();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PROJECTION_REQUEST_CODE && resultCode == RESULT_OK && data != null) {
            startPlaybackCapture(resultCode, data);
        } else if (requestCode == PROJECTION_REQUEST_CODE) {
            status.setText("MediaProjection permission denied");
        }
    }

    private void startCapture() {
        new Thread(new Runnable() {
            @Override
            public void run() {
            try {
                if (delayMs > 0) Thread.sleep(delayMs);
                if (MODE_PROBE.equals(mode)) {
                    probe();
                } else if (MODE_SYNTHETIC.equals(mode)) {
                    syntheticPlayback();
                } else if (MODE_PLAYBACK_CAPTURE.equals(mode)) {
                    throw new IOException("playback capture requires projection result");
                } else {
                    capture();
                }
                writeCompleteMarker();
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        status.setText("Capture complete");
                    }
                });
            } catch (Exception error) {
                final String message = "Capture failed: " + error.getMessage();
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        status.setText(message);
                    }
                });
            }
            }
        }, "loopback-capture").start();
    }

    private void startPlaybackCapture(final int resultCode, final Intent data) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    playbackCapture(resultCode, data);
                    writeCompleteMarker();
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() { status.setText("Playback capture complete"); }
                    });
                } catch (final Exception error) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() { status.setText("Playback capture failed: " + error.getMessage()); }
                    });
                }
            }
        }, "playback-capture").start();
    }

    private void playbackCapture(int resultCode, Intent data) throws IOException {
        Intent serviceIntent = new Intent(this, ProjectionService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(serviceIntent);
        } else {
            startService(serviceIntent);
        }
        try {
            Thread.sleep(300);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IOException("foreground service startup interrupted");
        }
        MediaProjectionManager manager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        if (manager == null) throw new IOException("MediaProjection unavailable");
        MediaProjection projection = manager.getMediaProjection(resultCode, data);
        if (projection == null) throw new IOException("MediaProjection token unavailable");

        int inputMask = AudioFormat.CHANNEL_IN_MONO;
        int captureBuffer = Math.max(4096, AudioRecord.getMinBufferSize(
            PROBE_SAMPLE_RATE, inputMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioFormat format = new AudioFormat.Builder()
            .setSampleRate(PROBE_SAMPLE_RATE).setChannelMask(inputMask)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build();
        AudioPlaybackCaptureConfiguration.Builder captureBuilder =
            new AudioPlaybackCaptureConfiguration.Builder(projection);
        captureBuilder.addMatchingUid(captureUid > 0 ? captureUid : getApplicationInfo().uid);
        AudioPlaybackCaptureConfiguration configuration = captureBuilder.build();
        AudioRecord recorder = new AudioRecord.Builder()
            .setAudioFormat(format).setBufferSizeInBytes(captureBuffer)
            .setAudioPlaybackCaptureConfig(configuration).build();
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            projection.stop();
            throw new IOException("playback AudioRecord was not initialized");
        }

        int outputMask = AudioFormat.CHANNEL_OUT_MONO;
        int playbackBuffer = Math.max(4096, AudioTrack.getMinBufferSize(
            PROBE_SAMPLE_RATE, outputMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioTrack player = null;
        if (captureUid <= 0) {
            player = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(PROBE_SAMPLE_RATE)
                    .setChannelMask(outputMask).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(playbackBuffer).setTransferMode(AudioTrack.MODE_STREAM).build();
            if (player.getState() != AudioTrack.STATE_INITIALIZED) {
                recorder.release();
                projection.stop();
                throw new IOException("playback AudioTrack was not initialized");
            }
        }

        File files = artifactDirectory();
        String sourceName = captureUid > 0 ? "AudioPlaybackCapture:uid-" + captureUid : "AudioPlaybackCapture:own-uid";
        writeMetadata(files, MODE_PLAYBACK_CAPTURE, PROBE_SAMPLE_RATE, sourceName, CAPTURE_SECONDS);
        if (captureUid <= 0) writePcm(new File(files, "source.pcm"), signal(PROBE_SAMPLE_RATE, SOURCE_SECONDS));
        short[] buffer = new short[PROBE_SAMPLE_RATE / 10];
        recorder.startRecording();
        if (player != null) player.play();
        long deadline = System.nanoTime() + CAPTURE_SECONDS * 1000000000L;
        long sampleOffset = 0;
        try (FileOutputStream output = new FileOutputStream(new File(files, "capture.pcm"))) {
            while (System.nanoTime() < deadline) {
                if (player != null) {
                    fillSignal(buffer, sampleOffset, PROBE_SAMPLE_RATE);
                    int written = player.write(buffer, 0, buffer.length, AudioTrack.WRITE_BLOCKING);
                    if (written < 0) throw new IOException("playback write error " + written);
                    sampleOffset += written;
                }
                int read = recorder.read(buffer, 0, buffer.length, AudioRecord.READ_BLOCKING);
                if (read < 0) throw new IOException("playback capture read error " + read);
                writePcm(output, buffer, read);
            }
        } finally {
            if (player != null) {
                player.stop();
                player.release();
            }
            recorder.stop();
            recorder.release();
            projection.stop();
            stopService(serviceIntent);
        }
    }

    public static final class ProjectionService extends Service {
        private static final String CHANNEL_ID = "ushareiplay-projection";

        @Override
        public void onCreate() {
            super.onCreate();
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "UShareIPlay audio capture", NotificationManager.IMPORTANCE_LOW);
                NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
                if (manager != null) manager.createNotificationChannel(channel);
            }
            Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
            Notification notification = builder.setContentTitle("UShareIPlay audio capture")
                .setContentText("Capturing Android playback for the rooted emulator experiment")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now).build();
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(7002, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
            } else {
                startForeground(7002, notification);
            }
        }

        @Override
        public int onStartCommand(Intent intent, int flags, int startId) {
            return START_NOT_STICKY;
        }

        @Override
        public android.os.IBinder onBind(Intent intent) { return null; }
    }

    private void capture() throws IOException {
        short[] source = signal();
        int channelMask = AudioFormat.CHANNEL_OUT_MONO;
        AudioFormat playbackFormat = new AudioFormat.Builder()
            .setSampleRate(LOOPBACK_SAMPLE_RATE).setChannelMask(channelMask)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build();
        int playbackBuffer = Math.max(source.length * 2, AudioTrack.getMinBufferSize(LOOPBACK_SAMPLE_RATE, channelMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioTrack player = new AudioTrack.Builder()
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
            .setAudioFormat(playbackFormat).setBufferSizeInBytes(playbackBuffer)
            .setTransferMode(AudioTrack.MODE_STATIC).build();
        player.write(source, 0, source.length);

        int inputMask = AudioFormat.CHANNEL_IN_MONO;
        int captureBuffer = Math.max(4096, AudioRecord.getMinBufferSize(LOOPBACK_SAMPLE_RATE, inputMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioRecord recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, LOOPBACK_SAMPLE_RATE, inputMask, AudioFormat.ENCODING_PCM_16BIT, captureBuffer);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            throw new IOException("AudioRecord was not initialized");
        }

        File files = getExternalFilesDir(Environment.DIRECTORY_MUSIC);
        if (files == null) throw new IOException("external files unavailable");
        writePcm(new File(files, "source.pcm"), source);
        recorder.startRecording();
        player.play();
        short[] buffer = new short[captureBuffer / 2];
        int remaining = LOOPBACK_SAMPLE_RATE * CAPTURE_SECONDS;
        try (FileOutputStream output = new FileOutputStream(new File(files, "capture.pcm"))) {
            while (remaining > 0) {
                int read = recorder.read(buffer, 0, Math.min(buffer.length, remaining), AudioRecord.READ_BLOCKING);
                if (read < 0) throw new IOException("AudioRecord error " + read);
                writePcm(output, buffer, read);
                remaining -= read;
            }
        } finally {
            player.stop();
            player.release();
            recorder.stop();
            recorder.release();
        }
    }

    private void probe() throws IOException {
        int channelMask = AudioFormat.CHANNEL_IN_MONO;
        int captureBuffer = Math.max(4096, AudioRecord.getMinBufferSize(
            PROBE_SAMPLE_RATE, channelMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioRecord recorder = new AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            PROBE_SAMPLE_RATE,
            channelMask,
            AudioFormat.ENCODING_PCM_16BIT,
            captureBuffer);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            throw new IOException("AudioRecord probe was not initialized");
        }
        File files = artifactDirectory();
        writeMetadata(files, MODE_PROBE, PROBE_SAMPLE_RATE, "VOICE_COMMUNICATION", CAPTURE_SECONDS);
        recorder.startRecording();
        short[] buffer = new short[captureBuffer / 2];
        int remaining = PROBE_SAMPLE_RATE * CAPTURE_SECONDS;
        try (FileOutputStream output = new FileOutputStream(new File(files, "capture.pcm"))) {
            while (remaining > 0) {
                int read = recorder.read(buffer, 0, Math.min(buffer.length, remaining), AudioRecord.READ_BLOCKING);
                if (read < 0) throw new IOException("AudioRecord probe error " + read);
                writePcm(output, buffer, read);
                remaining -= read;
            }
        } finally {
            recorder.stop();
            recorder.release();
        }
    }

    private void syntheticPlayback() throws IOException {
        int channelMask = AudioFormat.CHANNEL_OUT_MONO;
        int bufferSize = Math.max(4096, AudioTrack.getMinBufferSize(
            PROBE_SAMPLE_RATE, channelMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioTrack player = new AudioTrack.Builder()
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
            .setAudioFormat(new AudioFormat.Builder().setSampleRate(PROBE_SAMPLE_RATE)
                .setChannelMask(channelMask).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build();
        if (player.getState() != AudioTrack.STATE_INITIALIZED) {
            throw new IOException("Synthetic playback was not initialized");
        }
        File files = artifactDirectory();
        writeMetadata(files, MODE_SYNTHETIC, PROBE_SAMPLE_RATE, "USAGE_MEDIA", SYNTHETIC_SECONDS);
        short[] buffer = new short[PROBE_SAMPLE_RATE / 10];
        writePcm(new File(files, "source.pcm"), signal(PROBE_SAMPLE_RATE, 5));
        player.play();
        long deadline = System.nanoTime() + SYNTHETIC_SECONDS * 1000000000L;
        try {
            long sampleOffset = 0;
            while (System.nanoTime() < deadline) {
                fillSignal(buffer, sampleOffset, PROBE_SAMPLE_RATE);
                int written = player.write(buffer, 0, buffer.length, AudioTrack.WRITE_BLOCKING);
                if (written < 0) throw new IOException("Synthetic playback error " + written);
                sampleOffset += written;
            }
        } finally {
            player.stop();
            player.release();
        }
    }

    private File artifactDirectory() throws IOException {
        File files = getExternalFilesDir(Environment.DIRECTORY_MUSIC);
        if (files == null) throw new IOException("external files unavailable");
        if (!files.exists() && !files.mkdirs()) throw new IOException("cannot create artifact directory");
        return files;
    }

    private void writeCompleteMarker() throws IOException {
        File marker = new File(artifactDirectory(), "complete.json");
        try (FileOutputStream output = new FileOutputStream(marker)) {
            output.write(("{\"mode\":\"" + mode + "\",\"status\":\"complete\"}\n").getBytes("UTF-8"));
        }
    }

    private static void writeMetadata(File directory, String mode, int sampleRate, String source, int seconds) throws IOException {
        File metadata = new File(directory, "metadata.json");
        String json = "{\"mode\":\"" + mode + "\",\"sample_rate\":" + sampleRate
            + ",\"audio_source\":\"" + source + "\",\"duration_seconds\":" + seconds + "}\n";
        try (FileOutputStream output = new FileOutputStream(metadata)) {
            output.write(json.getBytes("UTF-8"));
        }
    }

    private static short[] signal() {
        return signal(LOOPBACK_SAMPLE_RATE, SOURCE_SECONDS);
    }

    private static short[] signal(int sampleRate, int seconds) {
        short[] samples = new short[sampleRate * seconds];
        for (int index = 0; index < samples.length; index++) {
            double time = (double) index / sampleRate;
            double value = 0.45 * Math.sin(2 * Math.PI * 440 * time)
                + 0.10 * Math.sin(2 * Math.PI * 997 * time);
            samples[index] = (short) (value * Short.MAX_VALUE);
        }
        return samples;
    }

    private static void fillSignal(short[] samples, long offset, int sampleRate) {
        for (int index = 0; index < samples.length; index++) {
            double time = (double) (offset + index) / sampleRate;
            double value = 0.45 * Math.sin(2 * Math.PI * 440 * time)
                + 0.10 * Math.sin(2 * Math.PI * 997 * time);
            samples[index] = (short) (value * Short.MAX_VALUE);
        }
    }

    private static void writePcm(File output, short[] samples) throws IOException {
        try (FileOutputStream stream = new FileOutputStream(output)) {
            writePcm(stream, samples, samples.length);
        }
    }

    private static void writePcm(FileOutputStream stream, short[] samples, int count) throws IOException {
        byte[] bytes = new byte[count * 2];
        for (int index = 0; index < count; index++) {
            bytes[index * 2] = (byte) (samples[index] & 0xff);
            bytes[index * 2 + 1] = (byte) ((samples[index] >>> 8) & 0xff);
        }
        stream.write(bytes);
    }
}
