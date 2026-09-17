plugins {
    java
}

java {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(11)
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("com.prowidesoftware:pw-swift-core:SRU2025-10.3.19")
    implementation("com.prowidesoftware:pw-iso20022:SRU2025-10.3.10")
    implementation("com.fasterxml.jackson.core:jackson-databind:2.18.2")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}

tasks.register<Jar>("fatJar") {
    group = "build"
    description = "Jar autocontenido: FIN stdin -> CA_ES_SWIFT_MT_FACTS_V1 stdout"
    archiveBaseName.set("iso-adapter")
    archiveVersion.set("")
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    manifest {
        attributes("Main-Class" to "caes.iso.IsoAdapter")
    }
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({
        configurations.runtimeClasspath.get().map {
            if (it.isDirectory) it else zipTree(it)
        }
    })
}
