package com.ruach.scribe

import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.SweepGradient
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.animation.LinearInterpolator
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.sin

class RuachOverlayService : Service() {

    enum class OverlayState {
        IDLE,
        LISTENING,
        LOCKED,
        PROCESSING
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var windowManager: WindowManager
    private lateinit var config: ConfigManager
    private var overlayView: RuachFloatingView? = null
    private var layoutParams: WindowManager.LayoutParams? = null
    private lateinit var recorder: AudioRecorder

    override fun onCreate() {
        super.onCreate()
        config = ConfigManager(this)
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        recorder = AudioRecorder(
            onAmplitude = { level ->
                overlayView?.setAudioLevel(level)
            }
        )
        startForeground(NOTIFICATION_ID, buildNotification())
        showFloatingOverlay()
        _isRunning.value = true

        serviceScope.launch {
            RuachAccessibilityService.isTextFieldFocused.collect { focused ->
                val view = overlayView ?: return@collect
                val shouldShow = focused || view.state != OverlayState.IDLE
                view.visibility = if (shouldShow) View.VISIBLE else View.GONE
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_UPDATE_POSITION) {
            applyConfiguredAnchorPosition()
        } else if (intent?.action == ACTION_STOP_SERVICE) {
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        _isRunning.value = false
        try {
            if (recorder.isRecording) {
                recorder.stopBytes()
            }
        } catch (_: Exception) {
        }
        overlayView?.let { view ->
            try {
                windowManager.removeView(view)
            } catch (_: Exception) {
            }
        }
        overlayView = null
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun buildNotification(): Notification {
        val channelId = "ruach_scribe_overlay_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Ruach Scribe Floating Dictation",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps the floating Ruach Scribe voice dictation bubble active."
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }

        val openAppIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, RuachOverlayService::class.java).apply { action = ACTION_STOP_SERVICE },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, channelId)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }

        return builder
            .setContentTitle("Ruach Scribe Active")
            .setContentText("Hold bubble to talk & release to paste • Double-tap to lock")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(openAppIntent)
            .addAction(
                Notification.Action.Builder(
                    null,
                    "Stop Bubble",
                    stopIntent
                ).build()
            )
            .setOngoing(true)
            .build()
    }

    private fun showFloatingOverlay() {
        val density = resources.displayMetrics.density
        val pillW = (56 * density).toInt()
        val pillH = (56 * density).toInt()

        val params = WindowManager.LayoutParams(
            pillW,
            pillH,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        )

        layoutParams = params
        params.gravity = Gravity.BOTTOM or Gravity.END
        params.x = (16 * density).toInt()
        params.y = (320 * density).toInt()

        val view = RuachFloatingView(this)
        view.visibility = if (RuachAccessibilityService.isTextFieldFocused.value) View.VISIBLE else View.GONE
        overlayView = view
        windowManager.addView(view, params)
    }

    private fun applyConfiguredAnchorPosition() {
        val params = layoutParams ?: return
        val view = overlayView ?: return
        applyAnchorToParams(params)
        try {
            windowManager.updateViewLayout(view, params)
        } catch (_: Exception) {
        }
    }

    private fun applyAnchorToParams(params: WindowManager.LayoutParams) {
        val density = resources.displayMetrics.density
        val marginX = (18 * density).toInt()
        val marginY = (48 * density).toInt()

        params.x = marginX
        params.y = marginY

        params.gravity = when (config.overlayPosition) {
            "bottom_center" -> {
                params.x = 0
                Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            }
            "bottom_right" -> Gravity.BOTTOM or Gravity.END
            "bottom_left" -> Gravity.BOTTOM or Gravity.START
            "left_center" -> {
                params.y = 0
                Gravity.CENTER_VERTICAL or Gravity.START
            }
            "right_center" -> {
                params.y = 0
                Gravity.CENTER_VERTICAL or Gravity.END
            }
            "top_center" -> {
                params.x = 0
                Gravity.TOP or Gravity.CENTER_HORIZONTAL
            }
            "top_right" -> Gravity.TOP or Gravity.END
            "top_left" -> Gravity.TOP or Gravity.START
            else -> Gravity.BOTTOM or Gravity.END
        }
    }

    private fun vibrateTick() {
        try {
            val vib = getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib.vibrate(VibrationEffect.createOneShot(25, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vib.vibrate(25)
            }
        } catch (_: Exception) {
        }
    }

    private fun onStartDictation(locked: Boolean) {
        if (overlayView?.state == OverlayState.PROCESSING) return
        val apiKey = config.apiKey
        if (apiKey.isBlank()) {
            HistoryManager.setLastError("Missing Google Gemini API Key. Please add it in Settings.")
            Toast.makeText(
                this,
                "Ruach Scribe: Please enter your Gemini API Key in Settings.",
                Toast.LENGTH_LONG
            ).show()
            return
        }

        try {
            if (!recorder.isRecording) {
                recorder.start()
                vibrateTick()
            }
            overlayView?.setOverlayState(
                if (locked) OverlayState.LOCKED else OverlayState.LISTENING
            )
        } catch (e: Exception) {
            overlayView?.setOverlayState(OverlayState.IDLE)
            val msg = e.message ?: "Microphone error"
            HistoryManager.setLastError(msg)
            Toast.makeText(this, "Ruach Scribe: $msg", Toast.LENGTH_LONG).show()
        }
    }

    private fun onCancelDictation() {
        try {
            recorder.stopBytes()
        } catch (_: Exception) {
        }
        overlayView?.setOverlayState(OverlayState.IDLE)
    }

    private fun onStopAndTranscribe() {
        if (overlayView?.state == OverlayState.PROCESSING) return
        val wavBytes = try {
            recorder.stopBytes()
        } catch (e: Exception) {
            overlayView?.setOverlayState(OverlayState.IDLE)
            HistoryManager.setLastError("Audio capture error: ${e.message}")
            return
        }

        if (wavBytes == null || wavBytes.size < 100) {
            overlayView?.setOverlayState(OverlayState.IDLE)
            return
        }

        vibrateTick()
        overlayView?.setOverlayState(OverlayState.PROCESSING)

        val apiKey = config.apiKey
        val modelName = config.modelName
        val systemPrompt = config.systemPrompt
        val t0 = SystemClock.elapsedRealtime()

        serviceScope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    GeminiTranscriber.transcribeBytes(
                        wavBytes = wavBytes,
                        apiKey = apiKey,
                        systemPrompt = systemPrompt,
                        modelName = modelName
                    )
                }
                val elapsedSec = (SystemClock.elapsedRealtime() - t0) / 1000.0
                overlayView?.setOverlayState(OverlayState.IDLE)
                HistoryManager.setLastError("")

                if (result.cleanedText.isNotBlank() || result.rawText.isNotBlank()) {
                    HistoryManager.addEntry(
                        context = this@RuachOverlayService,
                        rawText = result.rawText.ifBlank { result.cleanedText },
                        cleanedText = result.cleanedText,
                        latencySec = elapsedSec,
                        modelName = modelName
                    )
                }

                if (result.cleanedText.isNotBlank()) {
                    val autoPasted = RuachAccessibilityService.copyAndAutoPaste(
                        this@RuachOverlayService,
                        result.cleanedText
                    )
                    if (!autoPasted) {
                        Toast.makeText(
                            this@RuachOverlayService,
                            "Copied to clipboard (enable Ruach Auto-Paste in Accessibility to auto-type)",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            } catch (e: Exception) {
                overlayView?.setOverlayState(OverlayState.IDLE)
                val errMsg = e.message ?: "Transcription error"
                HistoryManager.setLastError(errMsg)
                Toast.makeText(
                    this@RuachOverlayService,
                    "Ruach Error: $errMsg",
                    Toast.LENGTH_LONG
                ).show()
            }
        }
    }

    /**
     * Custom floating view rendering the ethereal Ruach aura and handling:
     * - Hold-to-Talk (>= 300ms hold -> release to transcribe)
     * - Double-Tap to Lock (< 420ms between taps -> hands-free lock; double-tap to stop)
     * - Dragging to reposition on screen
     */
    inner class RuachFloatingView(context: Context) : View(context) {
        var state: OverlayState = OverlayState.IDLE
            private set

        private var phase = 0f
        private var swirlAngle = 0f
        private var audioLevel = 0f
        private var smoothedLevel = 0f

        private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 3.2f
        }
        private val orbPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val swirlPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 7f
            strokeCap = Paint.Cap.ROUND
        }
        private val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(242, 230, 252, 255)
            textSize = 13f * resources.displayMetrics.scaledDensity
            isFakeBoldText = true
        }
        private val subPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.argb(200, 145, 205, 225)
            textSize = 10.5f * resources.displayMetrics.scaledDensity
        }

        private val pillRect = RectF()
        private val arcRect = RectF()

        private val mainHandler = Handler(Looper.getMainLooper())
        private var pressDownTime = 0L
        private var lastTapReleaseTime = 0L
        private var lockedFirstTapTime = 0L
        private var justLockedOnThisPress = false
        private var isDragging = false
        private var downRawX = 0f
        private var downRawY = 0f
        private var startParamX = 0
        private var startParamY = 0

        private val singleTapCancelRunnable = Runnable {
            if (state == OverlayState.LISTENING) {
                onCancelDictation()
            }
        }

        private val animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 1000L
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            addUpdateListener {
                phase += 0.065f
                swirlAngle = (swirlAngle + 5.2f) % 360f
                smoothedLevel = smoothedLevel * 0.55f + audioLevel * 0.45f
                invalidate()
            }
        }

        init {
            animator.start()
        }

        fun setAudioLevel(level: Float) {
            audioLevel = level.coerceIn(0f, 1f)
        }

        fun setOverlayState(newState: OverlayState) {
            state = newState
            if (newState == OverlayState.IDLE) {
                audioLevel = 0f
                smoothedLevel = 0f
            }
            val params = layoutParams as? WindowManager.LayoutParams
            if (params != null && isAttachedToWindow) {
                val d = resources.displayMetrics.density
                val targetW = if (newState == OverlayState.LISTENING || newState == OverlayState.LOCKED) {
                    (116 * d).toInt()
                } else {
                    (56 * d).toInt()
                }
                if (params.width != targetW) {
                    params.width = targetW
                    try {
                        windowManager.updateViewLayout(this, params)
                    } catch (_: Exception) {
                    }
                }
            }
            invalidate()
        }

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouchEvent(event: MotionEvent): Boolean {
            val params = layoutParams as? WindowManager.LayoutParams ?: return false
            val touchSlop = 18f * resources.displayMetrics.density

            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    isDragging = false
                    downRawX = event.rawX
                    downRawY = event.rawY
                    startParamX = params.x
                    startParamY = params.y
                    return true
                }

                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downRawX
                    val dy = event.rawY - downRawY
                    if (!isDragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) {
                        isDragging = true
                    }
                    if (isDragging) {
                        val horizSign = if ((params.gravity and Gravity.END) == Gravity.END) -1 else 1
                        val vertSign = if ((params.gravity and Gravity.BOTTOM) == Gravity.BOTTOM) -1 else 1
                        params.x = startParamX + (dx * horizSign).toInt()
                        params.y = startParamY + (dy * vertSign).toInt()
                        try {
                            windowManager.updateViewLayout(this, params)
                        } catch (_: Exception) {
                        }
                    }
                    return true
                }

                MotionEvent.ACTION_UP -> {
                    if (isDragging) {
                        isDragging = false
                        return true
                    }
                    when (state) {
                        OverlayState.IDLE -> onStartDictation(locked = false)
                        OverlayState.LISTENING, OverlayState.LOCKED -> onStopAndTranscribe()
                        OverlayState.PROCESSING -> {}
                    }
                    return true
                }

                MotionEvent.ACTION_CANCEL -> {
                    isDragging = false
                    return true
                }
            }
            return super.onTouchEvent(event)
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val d = resources.displayMetrics.density
            val w = width.toFloat()
            val h = height.toFloat()

            pillRect.set(4f * d, 4f * d, w - 4f * d, h - 4f * d)
            bgPaint.color = Color.argb(225, 9, 16, 26)
            canvas.drawRoundRect(pillRect, 26f * d, 26f * d, bgPaint)

            borderPaint.color = when (state) {
                OverlayState.LOCKED -> Color.argb(180, 128, 255, 219)
                OverlayState.LISTENING -> Color.argb(160, 100, 223, 223)
                OverlayState.PROCESSING -> Color.argb(160, 116, 185, 255)
                OverlayState.IDLE -> Color.argb(95, 130, 235, 255)
            }
            canvas.drawRoundRect(pillRect, 26f * d, 26f * d, borderPaint)

            val cy = h / 2f

            when (state) {
                OverlayState.IDLE -> {
                    drawListeningAura(canvas, w / 2f, cy, d, active = false, locked = false)
                }
                OverlayState.LISTENING, OverlayState.LOCKED -> {
                    drawListeningAura(canvas, 28f * d, cy, d, active = true, locked = true)
                    drawCheckMark(canvas, 86f * d, cy, d)
                }
                OverlayState.PROCESSING -> {
                    drawProcessingSwirl(canvas, w / 2f, cy, d)
                }
            }
        }

        private fun drawCheckMark(canvas: Canvas, cx: Float, cy: Float, d: Float) {
            swirlPaint.shader = null
            swirlPaint.color = Color.argb(245, 128, 255, 219)
            swirlPaint.strokeWidth = 3.0f * d
            swirlPaint.strokeCap = Paint.Cap.ROUND
            swirlPaint.strokeJoin = Paint.Join.ROUND
            val path = android.graphics.Path().apply {
                moveTo(cx - 8f * d, cy + 0.5f * d)
                lineTo(cx - 2f * d, cy + 6.5f * d)
                lineTo(cx + 9f * d, cy - 6.5f * d)
            }
            canvas.drawPath(path, swirlPaint)
        }

        private fun drawListeningAura(
            canvas: Canvas,
            cx: Float,
            cy: Float,
            d: Float,
            active: Boolean,
            locked: Boolean
        ) {
            val breath = ((sin(phase.toDouble()) + 1.0) * 0.5).toFloat()
            val expansion = if (active) (breath * 4.5f + smoothedLevel * 18f) * d else (breath * 2.5f) * d

            val outerRadius = (16f * d + expansion).coerceAtLeast(4f)
            orbPaint.shader = RadialGradient(
                cx,
                cy,
                outerRadius,
                intArrayOf(
                    if (locked) Color.argb(200, 128, 255, 219) else Color.argb(165, 100, 223, 223),
                    Color.argb(90, 86, 207, 225),
                    Color.argb(0, 86, 207, 225)
                ),
                floatArrayOf(0f, 0.6f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawCircle(cx, cy, outerRadius, orbPaint)

            val coreRadius = (6.5f * d + (if (active) smoothedLevel * 6.5f * d else 0f)).coerceAtLeast(2f)
            orbPaint.shader = RadialGradient(
                cx,
                cy,
                coreRadius,
                intArrayOf(
                    Color.argb(255, 255, 255, 255),
                    Color.argb(210, 210, 252, 255),
                    Color.argb(0, 160, 240, 255)
                ),
                floatArrayOf(0f, 0.75f, 1f),
                Shader.TileMode.CLAMP
            )
            canvas.drawCircle(cx, cy, coreRadius, orbPaint)
        }

        private fun drawProcessingSwirl(canvas: Canvas, cx: Float, cy: Float, d: Float) {
            val r = 14f * d
            canvas.save()
            canvas.rotate(swirlAngle, cx, cy)
            swirlPaint.shader = SweepGradient(
                cx,
                cy,
                intArrayOf(
                    Color.argb(250, 255, 255, 255),
                    Color.argb(200, 100, 223, 223),
                    Color.argb(40, 116, 185, 255),
                    Color.argb(200, 128, 255, 219),
                    Color.argb(250, 255, 255, 255)
                ),
                null
            )
            swirlPaint.strokeWidth = 3f * d
            canvas.drawCircle(cx, cy, r, swirlPaint)
            canvas.restore()

            arcRect.set(cx - 8f * d, cy - 8f * d, cx + 8f * d, cy + 8f * d)
            swirlPaint.shader = null
            swirlPaint.color = Color.argb(200, 235, 255, 255)
            swirlPaint.strokeWidth = 1.8f * d
            canvas.drawArc(arcRect, -swirlAngle * 1.3f, 110f, false, swirlPaint)
            canvas.drawArc(arcRect, -swirlAngle * 1.3f + 180f, 110f, false, swirlPaint)
        }
    }

    companion object {
        const val NOTIFICATION_ID = 1001
        const val ACTION_UPDATE_POSITION = "com.ruach.scribe.UPDATE_POSITION"
        const val ACTION_STOP_SERVICE = "com.ruach.scribe.STOP_SERVICE"

        private val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()
    }
}
