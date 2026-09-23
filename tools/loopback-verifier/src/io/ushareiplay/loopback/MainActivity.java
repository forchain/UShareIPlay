package io.ushareiplay.loopback;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Environment;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;

public final class MainActivity extends Activity {
    private static final int SAMPLE_RATE = 8000;
    private static final int SOURCE_SECONDS = 5;
    private static final int CAPTURE_SECONDS = 7;
    private TextView status;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        status = new TextView(this);
        status.setText("Preparing loopback capture");
        setContentView(status);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        } else {
            startCapture();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(requestCode, permissions, grants);
        if (requestCode == 1 && grants.length == 1 && grants[0] == PackageManager.PERMISSION_GRANTED) {
            startCapture();
        } else {
            status.setText("RECORD_AUDIO permission denied");
        }
    }

    private void startCapture() {
        new Thread(new Runnable() {
            @Override
            public void run() {
            try {
                capture();
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

    private void capture() throws IOException {
        short[] source = signal();
        int channelMask = AudioFormat.CHANNEL_OUT_MONO;
        AudioFormat playbackFormat = new AudioFormat.Builder()
            .setSampleRate(SAMPLE_RATE).setChannelMask(channelMask)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build();
        int playbackBuffer = Math.max(source.length * 2, AudioTrack.getMinBufferSize(SAMPLE_RATE, channelMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioTrack player = new AudioTrack.Builder()
            .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).build())
            .setAudioFormat(playbackFormat).setBufferSizeInBytes(playbackBuffer)
            .setTransferMode(AudioTrack.MODE_STATIC).build();
        player.write(source, 0, source.length);

        int inputMask = AudioFormat.CHANNEL_IN_MONO;
        int captureBuffer = Math.max(4096, AudioRecord.getMinBufferSize(SAMPLE_RATE, inputMask, AudioFormat.ENCODING_PCM_16BIT));
        AudioRecord recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE, inputMask, AudioFormat.ENCODING_PCM_16BIT, captureBuffer);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            throw new IOException("AudioRecord was not initialized");
        }

        File files = getExternalFilesDir(Environment.DIRECTORY_MUSIC);
        if (files == null) throw new IOException("external files unavailable");
        writePcm(new File(files, "source.pcm"), source);
        recorder.startRecording();
        player.play();
        short[] buffer = new short[captureBuffer / 2];
        int remaining = SAMPLE_RATE * CAPTURE_SECONDS;
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

    private static short[] signal() {
        short[] samples = new short[SAMPLE_RATE * SOURCE_SECONDS];
        for (int index = 0; index < samples.length; index++) {
            double time = (double) index / SAMPLE_RATE;
            double value = 0.45 * Math.sin(2 * Math.PI * 440 * time)
                + 0.10 * Math.sin(2 * Math.PI * 997 * time);
            samples[index] = (short) (value * Short.MAX_VALUE);
        }
        return samples;
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
