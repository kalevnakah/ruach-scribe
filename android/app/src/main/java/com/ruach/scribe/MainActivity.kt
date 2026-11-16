package com.ruach.scribe

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver

private val RuachDarkBg = Color(0xFF0D1520)
private val RuachCardBg = Color(0xFF142232)
private val RuachBorder = Color(0xFF284660)
private val RuachCyan = Color(0xFF64DFDF)
private val RuachMint = Color(0xFF80FFDB)
private val RuachTealBtn = Color(0xFF197278)
private val RuachAmber = Color(0xFFFFD166)
private val RuachTextPrimary = Color(0xFFF0FAFF)
private val RuachTextSecondary = Color(0xFF8ECAE6)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HistoryManager.load(this)
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    background = RuachDarkBg,
                    surface = RuachCardBg,
                    primary = RuachCyan,
                    secondary = RuachMint,
                    onBackground = RuachTextPrimary,
                    onSurface = RuachTextPrimary
                )
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = RuachDarkBg
                ) {
                    RuachMainScreen()
                }
            }
        }
    }
}

@Composable
fun RuachMainScreen() {
    val context = LocalContext.current
    val config = remember { ConfigManager(context) }

    var selectedTab by remember { mutableIntStateOf(0) }
    val isServiceRunning by RuachOverlayService.isRunning.collectAsState()
    val historyEntries by HistoryManager.entries.collectAsState()
    val lastError by HistoryManager.lastError.collectAsState()

    var hasMicPerm by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
        )
    }
    var hasOverlayPerm by remember { mutableStateOf(Settings.canDrawOverlays(context)) }
    var hasAccessibilityPerm by remember {
        mutableStateOf(RuachAccessibilityService.instance != null)
    }

    val micPermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        hasMicPerm = perms[Manifest.permission.RECORD_AUDIO] == true
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                hasMicPerm = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.RECORD_AUDIO
                ) == PackageManager.PERMISSION_GRANTED
                hasOverlayPerm = Settings.canDrawOverlays(context)
                hasAccessibilityPerm = RuachAccessibilityService.instance != null
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Header with Logo
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(bottom = 12.dp)
        ) {
            Image(
                painter = painterResource(id = R.drawable.ic_ruach_logo),
                contentDescription = "Ruach Scribe Logo",
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(12.dp))
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Ruach Scribe",
                    color = RuachMint,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "Hold bubble to talk & release to paste • 2x tap to lock",
                    color = RuachTextSecondary,
                    fontSize = 12.sp
                )
            }
            Button(
                onClick = {
                    if (!hasMicPerm) {
                        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            perms.add(Manifest.permission.POST_NOTIFICATIONS)
                        }
                        micPermLauncher.launch(perms.toTypedArray())
                        return@Button
                    }
                    if (!hasOverlayPerm) {
                        val intent = Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse("package:${context.packageName}")
                        )
                        context.startActivity(intent)
                        return@Button
                    }
                    val svcIntent = Intent(context, RuachOverlayService::class.java)
                    if (isServiceRunning) {
                        context.stopService(svcIntent)
                    } else {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                            context.startForegroundService(svcIntent)
                        } else {
                            context.startService(svcIntent)
                        }
                    }
                },
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (isServiceRunning) Color(0xFF9B2226) else RuachTealBtn
                ),
                shape = RoundedCornerShape(8.dp)
            ) {
                Text(
                    text = if (isServiceRunning) "Stop Bubble" else "Start Bubble",
                    color = Color.White,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        // Tabs: Settings vs Transcription History (Before & After)
        TabRow(
            selectedTabIndex = selectedTab,
            containerColor = RuachCardBg,
            contentColor = RuachMint,
            modifier = Modifier.clip(RoundedCornerShape(8.dp))
        ) {
            Tab(
                selected = selectedTab == 0,
                onClick = { selectedTab = 0 },
                text = { Text("Settings", fontWeight = FontWeight.SemiBold) }
            )
            Tab(
                selected = selectedTab == 1,
                onClick = { selectedTab = 1 },
                text = { Text("History (Before & After)", fontWeight = FontWeight.SemiBold) }
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        if (selectedTab == 0) {
            SettingsTabContent(
                config = config,
                lastError = lastError,
                hasMicPerm = hasMicPerm,
                hasOverlayPerm = hasOverlayPerm,
                hasAccessibilityPerm = hasAccessibilityPerm,
                onRequestMic = {
                    val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        perms.add(Manifest.permission.POST_NOTIFICATIONS)
                    }
                    micPermLauncher.launch(perms.toTypedArray())
                },
                onRequestOverlay = {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse("package:${context.packageName}")
                        )
                    )
                },
                onRequestAccessibility = {
                    context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                }
            )
        } else {
            HistoryTabContent(entries = historyEntries)
        }
    }
}

@Composable
fun SettingsTabContent(
    config: ConfigManager,
    lastError: String,
    hasMicPerm: Boolean,
    hasOverlayPerm: Boolean,
    hasAccessibilityPerm: Boolean,
    onRequestMic: () -> Unit,
    onRequestOverlay: () -> Unit,
    onRequestAccessibility: () -> Unit
) {
    val context = LocalContext.current
    var apiKey by remember { mutableStateOf(config.apiKey) }
    var showApiKey by remember { mutableStateOf(false) }
    var selectedModel by remember { mutableStateOf(config.modelName) }
    var selectedPosition by remember { mutableStateOf(config.overlayPosition) }
    var startOnBoot by remember { mutableStateOf(config.startOnBoot) }
    var systemPrompt by remember { mutableStateOf(config.systemPrompt) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        if (lastError.isNotBlank()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color(0xFF2B141C), RoundedCornerShape(8.dp))
                    .border(1.dp, Color(0xFFFF4D6D), RoundedCornerShape(8.dp))
                    .padding(10.dp)
            ) {
                Text(
                    text = "Last Error:\n$lastError",
                    color = Color(0xFFFFB3C1),
                    fontSize = 12.sp
                )
            }
        }

        // Android Permissions Status Card
        if (!hasMicPerm || !hasOverlayPerm || !hasAccessibilityPerm) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(RuachCardBg, RoundedCornerShape(8.dp))
                    .border(1.dp, RuachBorder, RoundedCornerShape(8.dp))
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = "Android Phone Setup Permissions:",
                    color = RuachAmber,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                if (!hasMicPerm) {
                    OutlinedButton(onClick = onRequestMic, modifier = Modifier.fillMaxWidth()) {
                        Text("1. Grant Microphone Permission", color = RuachTextPrimary)
                    }
                }
                if (!hasOverlayPerm) {
                    OutlinedButton(onClick = onRequestOverlay, modifier = Modifier.fillMaxWidth()) {
                        Text("2. Allow 'Display Over Other Apps' (Floating Bubble)", color = RuachTextPrimary)
                    }
                }
                if (!hasAccessibilityPerm) {
                    OutlinedButton(onClick = onRequestAccessibility, modifier = Modifier.fillMaxWidth()) {
                        Text("3. Enable 'Ruach Scribe Auto-Paste' in Accessibility", color = RuachTextPrimary)
                    }
                }
            }
        }

        // 1. Gemini API Key
        Text("Gemini API Key:", color = RuachTextSecondary, fontSize = 13.sp)
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = apiKey,
                onValueChange = { apiKey = it },
                placeholder = { Text("Enter Google Gemini API Key (AIza...)", fontSize = 13.sp) },
                visualTransformation = if (showApiKey) VisualTransformation.None else PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.weight(1f),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = RuachCyan,
                    unfocusedBorderColor = RuachBorder,
                    focusedContainerColor = RuachCardBg,
                    unfocusedContainerColor = RuachCardBg
                )
            )
            OutlinedButton(onClick = { showApiKey = !showApiKey }) {
                Text(if (showApiKey) "Hide" else "Show", color = RuachTextPrimary)
            }
        }

        // 2. Gemini Model Dropdown
        Text("Gemini Model:", color = RuachTextSecondary, fontSize = 13.sp)
        DropdownSelector(
            items = ConfigManager.MODEL_OPTIONS.map { it to it },
            selectedValue = selectedModel,
            onValueSelected = { selectedModel = it }
        )

        // 3. Overlay Position (8 Anchor Positions)
        Text("Floating Bubble Position:", color = RuachTextSecondary, fontSize = 13.sp)
        DropdownSelector(
            items = ConfigManager.POSITION_OPTIONS,
            selectedValue = selectedPosition,
            onValueSelected = { selectedPosition = it }
        )

        // 4. Autostart on Phone Boot
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .clickable { startOnBoot = !startOnBoot }
        ) {
            Checkbox(
                checked = startOnBoot,
                onCheckedChange = { startOnBoot = it },
                colors = CheckboxDefaults.colors(checkedColor = RuachTealBtn)
            )
            Text(
                text = "Start Ruach Scribe automatically in background on phone boot",
                color = RuachTextPrimary,
                fontSize = 13.sp
            )
        }

        // 5. System Prompt
        Text("System Prompt:", color = RuachTextSecondary, fontSize = 13.sp)
        OutlinedTextField(
            value = systemPrompt,
            onValueChange = { systemPrompt = it },
            modifier = Modifier
                .fillMaxWidth()
                .height(130.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = RuachCyan,
                unfocusedBorderColor = RuachBorder,
                focusedContainerColor = RuachCardBg,
                unfocusedContainerColor = RuachCardBg
            )
        )

        // Action Buttons
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            OutlinedButton(
                onClick = { systemPrompt = ConfigManager.DEFAULT_PROMPT }
            ) {
                Text("Reset Default Prompt", color = RuachTextPrimary)
            }

            Button(
                onClick = {
                    config.apiKey = apiKey
                    config.modelName = selectedModel
                    config.overlayPosition = selectedPosition
                    config.startOnBoot = startOnBoot
                    config.systemPrompt = systemPrompt

                    if (RuachOverlayService.isRunning.value) {
                        context.startService(
                            Intent(context, RuachOverlayService::class.java).apply {
                                action = RuachOverlayService.ACTION_UPDATE_POSITION
                            }
                        )
                    }
                    Toast.makeText(context, "Settings saved!", Toast.LENGTH_SHORT).show()
                },
                colors = ButtonDefaults.buttonColors(containerColor = RuachTealBtn)
            ) {
                Text("Save Settings", color = Color.White, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
fun HistoryTabContent(entries: List<HistoryEntry>) {
    val context = LocalContext.current
    var selectedIdx by remember(entries.size) { mutableIntStateOf(if (entries.isNotEmpty()) 0 else -1) }
    val selectedEntry = entries.getOrNull(selectedIdx)

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Section 1: Saved Transcriptions List
        Column(modifier = Modifier.weight(1.1f)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Saved Transcriptions: ${entries.size}",
                    color = RuachMint,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                OutlinedButton(
                    onClick = {
                        HistoryManager.clear(context)
                        selectedIdx = -1
                    }
                ) {
                    Text("Clear All History", color = RuachTextPrimary, fontSize = 12.sp)
                }
            }

            Spacer(modifier = Modifier.height(6.dp))

            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .background(RuachCardBg, RoundedCornerShape(8.dp))
                    .border(1.dp, RuachBorder, RoundedCornerShape(8.dp))
                    .padding(6.dp)
            ) {
                itemsIndexed(entries) { idx, item ->
                    val isSelected = idx == selectedIdx
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(if (isSelected) RuachTealBtn else Color.Transparent)
                            .clickable { selectedIdx = idx }
                            .padding(horizontal = 8.dp, vertical = 8.dp)
                    ) {
                        Text(
                            text = "[${item.timestamp}] (${item.latencySec}s) — ${item.cleanedText.replace("\n", " ")}",
                            color = if (isSelected) Color.White else RuachTextPrimary,
                            fontSize = 12.sp,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }
            }
        }

        // Section 2: Before Editing (Raw Verbatim Speech)
        Column(modifier = Modifier.weight(1f)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Before Editing (Raw Verbatim Speech):",
                    color = RuachAmber,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                OutlinedButton(
                    onClick = {
                        copyText(context, selectedEntry?.rawText ?: "")
                    }
                ) {
                    Text("Copy Before Text", color = RuachTextPrimary, fontSize = 12.sp)
                }
            }
            Spacer(modifier = Modifier.height(6.dp))
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color(0xFF1B1E2B), RoundedCornerShape(8.dp))
                    .border(1.dp, Color(0xFF5C4D26), RoundedCornerShape(8.dp))
                    .padding(10.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                Text(
                    text = selectedEntry?.rawText
                        ?: "Select a transcription above to view the raw speech before editing...",
                    color = Color(0xFFFFE8A3),
                    fontSize = 13.sp
                )
            }
        }

        // Section 3: After Editing (Cleaned Output Pasted)
        Column(modifier = Modifier.weight(1f)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "After Editing (Cleaned Output Pasted):",
                    color = RuachMint,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp
                )
                Button(
                    onClick = {
                        copyText(context, selectedEntry?.cleanedText ?: "")
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = RuachTealBtn)
                ) {
                    Text("Copy After Text", color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }
            Spacer(modifier = Modifier.height(6.dp))
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color(0xFF112630), RoundedCornerShape(8.dp))
                    .border(1.dp, Color(0xFF2EC4B6), RoundedCornerShape(8.dp))
                    .padding(10.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                Text(
                    text = selectedEntry?.cleanedText
                        ?: "Select a transcription above to view the cleaned text after editing...",
                    color = Color(0xFFE0FBFC),
                    fontSize = 13.sp
                )
            }
        }
    }
}

@Composable
fun DropdownSelector(
    items: List<Pair<String, String>>,
    selectedValue: String,
    onValueSelected: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    val currentLabel = items.firstOrNull { it.second == selectedValue }?.first ?: selectedValue

    Box(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(RuachCardBg, RoundedCornerShape(8.dp))
                .border(1.dp, RuachBorder, RoundedCornerShape(8.dp))
                .clickable { expanded = true }
                .padding(horizontal = 12.dp, vertical = 14.dp)
        ) {
            Text(text = currentLabel, color = RuachTextPrimary, fontSize = 13.sp)
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier.background(RuachCardBg)
        ) {
            items.forEach { (label, value) ->
                DropdownMenuItem(
                    text = { Text(label, color = RuachTextPrimary) },
                    onClick = {
                        onValueSelected(value)
                        expanded = false
                    }
                )
            }
        }
    }
}

private fun copyText(context: Context, text: String) {
    if (text.isBlank()) return
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("Ruach Scribe", text))
    Toast.makeText(context, "Copied to clipboard!", Toast.LENGTH_SHORT).show()
}
