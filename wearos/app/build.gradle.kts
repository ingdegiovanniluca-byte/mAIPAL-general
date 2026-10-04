plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val maipalUrl: String = (project.findProperty("maipalUrl") as String?) ?: "https://maipal.it/general"

android {
    namespace = "it.maipal.watch"
    compileSdk = 35

    defaultConfig {
        applicationId = "it.maipal.watch"
        minSdk = 30          // Wear OS 3: Galaxy Watch4 and newer
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
        buildConfigField("String", "MAIPAL_URL", "\"${maipalUrl.trimEnd('/')}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    val wear = "1.4.0"
    implementation(platform("androidx.compose:compose-bom:2024.10.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.wear.compose:compose-material:$wear")
    implementation("androidx.wear.compose:compose-foundation:$wear")
    implementation("androidx.wear.compose:compose-navigation:$wear")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
}
