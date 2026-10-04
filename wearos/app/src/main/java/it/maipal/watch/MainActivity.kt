package it.maipal.watch

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        setContent {
            MaipalTheme {
                val nav = rememberSwipeDismissableNavController()
                LaunchedEffect(Unit) {
                    vm.events.collect { go ->
                        when (go) {
                            Go.ANSWER -> if (nav.currentDestination?.route != "answer") nav.navigate("answer")
                            Go.HOME -> nav.navigate("home") { popUpTo(nav.graph.id) { inclusive = true } }
                            Go.PAIR -> nav.navigate("pair") { popUpTo(nav.graph.id) { inclusive = true } }
                        }
                    }
                }
                SwipeDismissableNavHost(navController = nav, startDestination = if (vm.linked) "home" else "pair") {
                    composable("pair") { PairScreen(vm) }
                    composable("home") {
                        HomeScreen(vm) { route ->
                            when (route) {
                                "chat" -> if (vm.answer != null) nav.navigate("answer")
                                else -> nav.navigate(route)
                            }
                        }
                    }
                    composable("answer") { AnswerScreen(vm) { nav.popBackStack() } }
                    composable("tasks") { TasksScreen(vm) }
                    composable("todos") { TodosScreen(vm) }
                    composable("lists") { ListsScreen(vm) { id -> nav.navigate("list/$id") } }
                    composable("list/{id}") { entry -> ListScreen(vm, entry.arguments?.getString("id").orEmpty()) }
                }
            }
        }
    }
}
