import java.security.MessageDigest

plugins {
    id("com.android.application")
}

// Release signing material comes only from the environment (CI secrets or a
// custodian's shell). It is never generated and never committed (§7.1).
val releaseKeystore: String? = System.getenv("KIOSK_KEYSTORE")?.takeIf { it.isNotBlank() }
val releaseKeystorePass: String? = System.getenv("KIOSK_KEYSTORE_PASS")?.takeIf { it.isNotBlank() }
val releaseKeyAlias: String? = System.getenv("KIOSK_KEYSTORE_ALIAS")?.takeIf { it.isNotBlank() }
val approvedCertSha256: String? = System.getenv("KIOSK_CERT_SHA256")
    ?.replace(":", "")?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
val hasReleaseSigning = releaseKeystore != null && releaseKeystorePass != null && releaseKeyAlias != null

android {
    namespace = "com.example.webkiosk"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.webkiosk"
        minSdk = 21
        targetSdk = 35
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseKeystore!!)
                storePassword = releaseKeystorePass
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeystorePass
            }
        }
    }

    buildTypes {
        debug {
            // Debug = debug-signed. Keep the manifest identical to the
            // tablets' APK: no android:debuggable on a Device Owner app.
            isDebuggable = false
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    lint {
        // Sideloaded over USB, never published to Play; targetSdk is pinned
        // to 35 by the architecture (§7, P1).
        disable += "ExpiredTargetSdkVersion"
    }
}

val requireReleaseSigning = tasks.register("requireReleaseSigning") {
    doLast {
        if (!hasReleaseSigning) {
            throw GradleException(
                "Release signing is not configured. Set KIOSK_KEYSTORE, KIOSK_KEYSTORE_PASS " +
                    "and KIOSK_KEYSTORE_ALIAS, or build the debug variant. " +
                    "A release key is never generated automatically."
            )
        }
    }
}

fun sha256Hex(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

// Records variant, APK digest and signer certificate digest next to the APK,
// and enforces KIOSK_CERT_SHA256 on release builds.
listOf("debug", "release").forEach { variant ->
    val cap = variant.replaceFirstChar { it.uppercase() }
    val apkDir = layout.buildDirectory.dir("outputs/apk/$variant")
    val apksignerJar = androidComponents.sdkComponents.sdkDirectory
        .map { it.file("build-tools/${android.buildToolsVersion}/lib/apksigner.jar").asFile }

    val verifyApk = tasks.register("verify${cap}Apk") {
        dependsOn("package$cap")
        outputs.upToDateWhen { false }
        doLast {
            val info = apkDir.get().file("apk-info.txt").asFile
            info.delete()
            val apk = apkDir.get().asFile.listFiles { f -> f.extension == "apk" }
                ?.singleOrNull()
                ?: throw GradleException("Expected exactly one APK in ${apkDir.get().asFile}")
            val java = File(System.getProperty("java.home"), "bin/java").path
            val proc = ProcessBuilder(java, "-jar", apksignerJar.get().path, "verify", "--print-certs", apk.path)
                .redirectErrorStream(true).start()
            val output = proc.inputStream.bufferedReader().readText()
            if (proc.waitFor() != 0) {
                throw GradleException("apksigner verify failed for ${apk.name}:\n$output")
            }
            val signers = Regex("""Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)""")
                .findAll(output).map { it.groupValues[1].lowercase() }.toList()
            val signer = signers.singleOrNull()
                ?: throw GradleException("Expected exactly one signer in ${apk.name}, found ${signers.size}:\n$output")
            if (variant == "release" && approvedCertSha256 != null && signer != approvedCertSha256) {
                apk.delete()
                throw GradleException(
                    "Release APK signer $signer does not match KIOSK_CERT_SHA256 $approvedCertSha256; deleted ${apk.name}"
                )
            }
            info.writeText(
                "variant=$variant\n" +
                    "apk=${apk.name}\n" +
                    "apk_sha256=${sha256Hex(apk.readBytes())}\n" +
                    "signer_cert_sha256=$signer\n"
            )
            logger.lifecycle("$variant APK ${apk.name} signer SHA-256: $signer")
        }
    }

    tasks.configureEach {
        if (variant == "release" && name == "preReleaseBuild") dependsOn(requireReleaseSigning)
        if (name == "assemble$cap") dependsOn(verifyApk)
    }
}
